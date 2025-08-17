from fastapi import FastAPI, HTTPException, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import asyncio
import json
import os
from typing import Optional, List
from datetime import datetime, timedelta
from pydantic import BaseModel

from models.db import create_tables, get_db
from models.schemas import PublishResult, AnalyticsData
from orchestrator.pipeline import VideoGenerationPipeline
from orchestrator.scheduler import PipelineScheduler
from publish.youtube import YouTubePublisher
from analytics.fetch import AnalyticsFetcher
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

# Pydantic models for API requests
class RunPipelineRequest(BaseModel):
    channel: str
    delay_minutes: Optional[int] = 0

class ScheduleDailyRequest(BaseModel):
    hour: int
    minute: int
    per_channel: int = 1

class UpdateScheduleRequest(BaseModel):
    channel: str
    time: str  # Format: "HH:MM"
    enabled: bool = True

# Global instances
pipeline = None
scheduler = None
youtube_publisher = None
analytics_fetcher = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    global pipeline, scheduler, youtube_publisher, analytics_fetcher
    
    # Startup
    logger.info("Starting Auto Shorts application...")
    
    # Create database tables
    await create_tables()
    
    # Initialize components
    pipeline = VideoGenerationPipeline()
    scheduler = PipelineScheduler()
    youtube_publisher = YouTubePublisher()
    analytics_fetcher = AnalyticsFetcher()
    
    # Start scheduler
    await scheduler.start_scheduler()
    
    logger.info("Auto Shorts application started")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Auto Shorts application...")
    
    if scheduler:
        await scheduler.stop_scheduler()
    
    logger.info("Auto Shorts application stopped")

app = FastAPI(
    title="Auto Shorts",
    description="Automated short-form video generation pipeline",
    version="1.0.0",
    lifespan=lifespan
)

# Templates setup
templates = Jinja2Templates(directory="templates")

# Create templates directory and basic templates
os.makedirs("templates", exist_ok=True)

# API Routes
@app.post("/run/once", response_model=PublishResult)
async def run_pipeline_once(request: RunPipelineRequest):
    """Run pipeline once for specified channel"""
    try:
        if request.delay_minutes > 0:
            # Schedule for later
            job_id = await scheduler.schedule_one_time_run(
                request.channel, 
                request.delay_minutes
            )
            
            if job_id:
                return {
                    "platform": "scheduled",
                    "video_id": job_id,
                    "url": f"http://localhost:8000/jobs/{job_id}",
                    "scheduled": True
                }
            else:
                raise HTTPException(status_code=500, detail="Failed to schedule pipeline run")
        
        else:
            # Run immediately
            result = await pipeline.run_full_pipeline(request.channel)
            
            if result:
                return result
            else:
                raise HTTPException(status_code=500, detail="Pipeline execution failed")
    
    except Exception as e:
        logger.error(f"Error in run_once endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/schedule/daily")
async def schedule_daily_runs(request: ScheduleDailyRequest):
    """Schedule daily pipeline runs"""
    try:
        scheduled_channels = []
        
        for channel_name in pipeline.channels_config.keys():
            time_str = f"{request.hour:02d}:{request.minute:02d}"
            
            success = await scheduler.modify_channel_schedule(
                channel_name, 
                time_str, 
                enabled=True
            )
            
            if success:
                scheduled_channels.append(channel_name)
        
        return {
            "scheduled_channels": scheduled_channels,
            "time": f"{request.hour:02d}:{request.minute:02d}",
            "per_channel": request.per_channel
        }
    
    except Exception as e:
        logger.error(f"Error in schedule_daily endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/ideas")
async def get_ideas(channel: str, limit: int = 20):
    """Get top topic ideas for a channel"""
    try:
        async for db in get_db():
            from sqlalchemy import select
            from models.db import TopicIdeaDB
            
            stmt = select(TopicIdeaDB).where(
                TopicIdeaDB.channel == channel,
                TopicIdeaDB.used == False
            ).order_by(TopicIdeaDB.score.desc()).limit(limit)
            
            result = await db.execute(stmt)
            db_ideas = result.scalars().all()
            
            ideas = []
            for db_idea in db_ideas:
                ideas.append({
                    "id": db_idea.id,
                    "title": db_idea.title,
                    "angle": db_idea.angle,
                    "keywords": db_idea.keywords,
                    "score": db_idea.score,
                    "source": db_idea.seed_source,
                    "created_at": db_idea.created_at.isoformat()
                })
            
            return {"ideas": ideas, "channel": channel}
    
    except Exception as e:
        logger.error(f"Error getting ideas: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Get pipeline status
        pipeline_status = pipeline.get_pipeline_status()
        
        # Get scheduler stats
        daily_stats = scheduler.get_daily_stats()
        
        # Get recent job status
        async for db in get_db():
            from sqlalchemy import select
            from models.db import PipelineJobDB
            
            stmt = select(PipelineJobDB).order_by(
                PipelineJobDB.started_at.desc()
            ).limit(5)
            
            result = await db.execute(stmt)
            recent_jobs = result.scalars().all()
            
            jobs = []
            for job in recent_jobs:
                jobs.append({
                    "id": job.id,
                    "channel": job.channel,
                    "status": job.status,
                    "started_at": job.started_at.isoformat(),
                    "completed_at": job.completed_at.isoformat() if job.completed_at else None
                })
        
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "pipeline": pipeline_status,
            "daily_stats": daily_stats,
            "recent_jobs": jobs
        }
    
    except Exception as e:
        logger.error(f"Error in health check: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

@app.post("/oauth/youtube/init")
async def init_youtube_oauth(channel: str):
    """Initialize YouTube OAuth flow"""
    try:
        auth_url = youtube_publisher.get_oauth_url(channel)
        
        if auth_url:
            return {"auth_url": auth_url, "channel": channel}
        else:
            raise HTTPException(status_code=500, detail="Failed to generate OAuth URL")
    
    except Exception as e:
        logger.error(f"Error initiating OAuth: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/oauth2callback")
async def youtube_oauth_callback(code: str, state: str):
    """Handle YouTube OAuth callback"""
    try:
        success = await youtube_publisher.handle_oauth_callback(code, state)
        
        if success:
            return {"message": f"OAuth completed successfully for {state}"}
        else:
            raise HTTPException(status_code=500, detail="OAuth callback failed")
    
    except Exception as e:
        logger.error(f"Error in OAuth callback: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/analytics/{video_id}")
async def get_video_analytics(video_id: str):
    """Get analytics for a specific video"""
    try:
        async for db in get_db():
            from sqlalchemy import select
            from models.db import AnalyticsDB
            
            stmt = select(AnalyticsDB).where(AnalyticsDB.video_id == video_id)
            result = await db.execute(stmt)
            analytics = result.scalar_one_or_none()
            
            if analytics:
                return {
                    "video_id": analytics.video_id,
                    "views": analytics.views,
                    "likes": analytics.likes,
                    "avg_view_duration_sec": analytics.avg_view_duration_sec,
                    "click_through_rate": analytics.click_through_rate,
                    "audience_retention": analytics.audience_retention,
                    "fetched_at": analytics.fetched_at.isoformat()
                }
            else:
                raise HTTPException(status_code=404, detail="Analytics not found")
    
    except Exception as e:
        logger.error(f"Error getting analytics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/dry-run")
async def dry_run_pipeline(request: RunPipelineRequest):
    """Run pipeline in dry mode (no publishing)"""
    try:
        result = await pipeline.dry_run(request.channel)
        return result
    
    except Exception as e:
        logger.error(f"Error in dry run: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Web UI Routes
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard"""
    try:
        # Get basic stats
        pipeline_status = pipeline.get_pipeline_status()
        daily_stats = scheduler.get_daily_stats()
        scheduled_jobs = scheduler.get_scheduled_jobs()
        
        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "pipeline_status": pipeline_status,
            "daily_stats": daily_stats,
            "scheduled_jobs": scheduled_jobs,
            "channels": list(pipeline.channels_config.keys())
        })
    
    except Exception as e:
        logger.error(f"Error loading dashboard: {e}")
        return HTMLResponse(f"<h1>Error loading dashboard</h1><p>{str(e)}</p>", status_code=500)

@app.get("/channels", response_class=HTMLResponse)
async def channels_page(request: Request):
    """Channels management page"""
    return templates.TemplateResponse("channels.html", {
        "request": request,
        "channels": pipeline.channels_config
    })

@app.get("/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request):
    """Jobs status page"""
    try:
        async for db in get_db():
            from sqlalchemy import select
            from models.db import PipelineJobDB
            
            stmt = select(PipelineJobDB).order_by(
                PipelineJobDB.started_at.desc()
            ).limit(50)
            
            result = await db.execute(stmt)
            jobs = result.scalars().all()
        
        return templates.TemplateResponse("jobs.html", {
            "request": request,
            "jobs": jobs
        })
    
    except Exception as e:
        logger.error(f"Error loading jobs page: {e}")
        return HTMLResponse(f"<h1>Error loading jobs</h1><p>{str(e)}</p>", status_code=500)

@app.post("/update-schedule")
async def update_schedule(request: UpdateScheduleRequest):
    """Update channel schedule"""
    try:
        success = await scheduler.modify_channel_schedule(
            request.channel,
            request.time,
            request.enabled
        )
        
        if success:
            return {"message": f"Schedule updated for {request.channel}"}
        else:
            raise HTTPException(status_code=500, detail="Failed to update schedule")
    
    except Exception as e:
        logger.error(f"Error updating schedule: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)