import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from orchestrator.pipeline import VideoGenerationPipeline
from analytics.fetch import AnalyticsFetcher
from analytics.learn import LearningEngine
from assets.broll import BRollProvider
from models.db import get_db, PipelineJobDB
from loguru import logger
import json
import os
from dotenv import load_dotenv

load_dotenv()

class PipelineScheduler:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.pipeline = VideoGenerationPipeline()
        self.analytics_fetcher = AnalyticsFetcher()
        self.learning_engine = LearningEngine()
        self.broll_provider = BRollProvider()
        
        self.max_daily_runs = int(os.getenv("MAX_DAILY_RUNS", "10"))
        self.default_schedule_time = "09:00"
        
        # Track daily run counts
        self.daily_run_counts = {}

    async def start_scheduler(self):
        """Start the scheduler"""
        try:
            # Set up default scheduled jobs for each channel
            await self._setup_default_schedules()
            
            # Set up maintenance jobs
            await self._setup_maintenance_jobs()
            
            self.scheduler.start()
            logger.info("Pipeline scheduler started")
            
        except Exception as e:
            logger.error(f"Error starting scheduler: {e}")

    async def stop_scheduler(self):
        """Stop the scheduler"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Pipeline scheduler stopped")

    async def _setup_default_schedules(self):
        """Set up default daily schedules for all channels"""
        for channel_name, config in self.pipeline.channels_config.items():
            local_time = config.get("local_time", self.default_schedule_time)
            hour, minute = map(int, local_time.split(":"))
            
            # Schedule daily video generation
            self.scheduler.add_job(
                self._run_scheduled_pipeline,
                CronTrigger(hour=hour, minute=minute),
                args=[channel_name],
                id=f"daily_{channel_name}",
                name=f"Daily video generation for {channel_name}",
                replace_existing=True
            )
            
            logger.info(f"Scheduled daily run for {channel_name} at {local_time}")

    async def _setup_maintenance_jobs(self):
        """Set up maintenance and analytics jobs"""
        # Analytics collection (every hour for recent videos)
        self.scheduler.add_job(
            self._collect_pending_analytics,
            CronTrigger(minute=0),  # Every hour
            id="analytics_collection",
            name="Collect video analytics",
            replace_existing=True
        )
        
        # Clean up old files (daily at 2 AM)
        self.scheduler.add_job(
            self._cleanup_old_files,
            CronTrigger(hour=2, minute=0),
            id="file_cleanup",
            name="Clean up old files",
            replace_existing=True
        )
        
        # Update learning data (daily at 3 AM)
        self.scheduler.add_job(
            self._update_learning_data,
            CronTrigger(hour=3, minute=0),
            id="learning_update",
            name="Update learning data",
            replace_existing=True
        )
        
        # Reset daily run counts (daily at midnight)
        self.scheduler.add_job(
            self._reset_daily_counts,
            CronTrigger(hour=0, minute=0),
            id="reset_daily_counts",
            name="Reset daily run counts",
            replace_existing=True
        )

    async def _run_scheduled_pipeline(self, channel_name: str):
        """Run pipeline for scheduled channel"""
        today = datetime.now().date()
        
        try:
            # Check daily run limit
            daily_count = self.daily_run_counts.get(today, 0)
            if daily_count >= self.max_daily_runs:
                logger.warning(f"Daily run limit reached ({self.max_daily_runs})")
                return
            
            logger.info(f"Running scheduled pipeline for {channel_name}")
            
            # Run the pipeline
            result = await self.pipeline.run_full_pipeline(channel_name)
            
            if result:
                # Update daily count
                self.daily_run_counts[today] = daily_count + 1
                
                # Schedule analytics collection for 24 hours later
                analytics_time = datetime.now() + timedelta(hours=24)
                self.scheduler.add_job(
                    self._collect_video_analytics,
                    DateTrigger(run_date=analytics_time),
                    args=[result.video_id, result.platform, channel_name],
                    id=f"analytics_{result.video_id}",
                    name=f"Collect analytics for {result.video_id}",
                    replace_existing=True
                )
                
                logger.info(f"Scheduled pipeline completed for {channel_name}: {result.url}")
            else:
                logger.error(f"Scheduled pipeline failed for {channel_name}")
                
        except Exception as e:
            logger.error(f"Error in scheduled pipeline for {channel_name}: {e}")

    async def _collect_pending_analytics(self):
        """Collect analytics for videos that are 24+ hours old"""
        try:
            cutoff_time = datetime.now() - timedelta(hours=24)
            
            async for db in get_db():
                from sqlalchemy import select
                
                # Get completed jobs from last 48 hours that have video_id
                stmt = select(PipelineJobDB).where(
                    PipelineJobDB.status == "success",
                    PipelineJobDB.video_id.isnot(None),
                    PipelineJobDB.completed_at >= cutoff_time - timedelta(hours=24),
                    PipelineJobDB.completed_at <= cutoff_time
                )
                
                result = await db.execute(stmt)
                jobs = result.scalars().all()
                
                for job in jobs:
                    await self._collect_video_analytics(
                        job.video_id, "youtube", job.channel
                    )
                    
                    # Small delay between requests
                    await asyncio.sleep(1)
        
        except Exception as e:
            logger.error(f"Error collecting pending analytics: {e}")

    async def _collect_video_analytics(
        self, 
        video_id: str, 
        platform: str, 
        channel_name: str
    ):
        """Collect analytics for a specific video"""
        try:
            logger.info(f"Collecting analytics for video {video_id}")
            
            # Get channel config for token path
            channel_config = self.pipeline.channels_config.get(channel_name)
            if not channel_config:
                logger.error(f"Channel config not found for {channel_name}")
                return
            
            token_path = channel_config.get("youtube_oauth_token")
            if not token_path:
                logger.error(f"No token path configured for {channel_name}")
                return
            
            # Fetch and store analytics
            success = await self.analytics_fetcher.fetch_and_store_analytics(
                video_id, platform, token_path
            )
            
            if success:
                logger.info(f"Analytics collected for {video_id}")
                
                # Trigger learning update
                await self._trigger_learning_update(video_id, channel_name)
            else:
                logger.warning(f"Failed to collect analytics for {video_id}")
        
        except Exception as e:
            logger.error(f"Error collecting analytics for {video_id}: {e}")

    async def _trigger_learning_update(self, video_id: str, channel_name: str):
        """Trigger learning update for a video"""
        try:
            # Get topic data for the video (from database)
            async for db in get_db():
                from sqlalchemy import select
                
                # Find the pipeline job for this video
                stmt = select(PipelineJobDB).where(
                    PipelineJobDB.video_id == video_id
                )
                result = await db.execute(stmt)
                job = result.scalar_one_or_none()
                
                if not job or not job.topic_id:
                    logger.warning(f"No topic data found for video {video_id}")
                    return
                
                # Get topic and script data
                from models.db import TopicIdeaDB, ScriptPackageDB
                
                topic_stmt = select(TopicIdeaDB).where(
                    TopicIdeaDB.id == job.topic_id
                )
                topic_result = await db.execute(topic_stmt)
                topic = topic_result.scalar_one_or_none()
                
                script_stmt = select(ScriptPackageDB).where(
                    ScriptPackageDB.topic_id == job.topic_id
                )
                script_result = await db.execute(script_stmt)
                script = script_result.scalar_one_or_none()
                
                if topic and script:
                    # Run learning analysis
                    await self.learning_engine.analyze_performance_and_learn(
                        video_id=video_id,
                        topic_keywords=topic.keywords,
                        hook=script.hook,
                        script=script.script_text,
                        channel=channel_name
                    )
                    
                    logger.info(f"Learning update completed for video {video_id}")
        
        except Exception as e:
            logger.error(f"Error in learning update for {video_id}: {e}")

    async def _cleanup_old_files(self):
        """Clean up old files to free space"""
        try:
            logger.info("Starting file cleanup")
            
            # Clean up old B-roll clips (7 days)
            self.broll_provider.cleanup_old_clips(days=7)
            
            # Clean up old renders (3 days)
            renders_dir = os.path.join(self.pipeline.content_root, "renders")
            if os.path.exists(renders_dir):
                cutoff_time = datetime.now().timestamp() - (3 * 24 * 60 * 60)
                
                for filename in os.listdir(renders_dir):
                    filepath = os.path.join(renders_dir, filename)
                    if os.path.isfile(filepath):
                        file_time = os.path.getmtime(filepath)
                        if file_time < cutoff_time:
                            os.remove(filepath)
                            logger.info(f"Cleaned up old render: {filename}")
            
            # Clean up old voice files (1 day)
            voice_dir = os.path.join(self.pipeline.content_root, "voice")
            if os.path.exists(voice_dir):
                cutoff_time = datetime.now().timestamp() - (1 * 24 * 60 * 60)
                
                for filename in os.listdir(voice_dir):
                    filepath = os.path.join(voice_dir, filename)
                    if os.path.isfile(filepath):
                        file_time = os.path.getmtime(filepath)
                        if file_time < cutoff_time:
                            os.remove(filepath)
                            logger.info(f"Cleaned up old voice file: {filename}")
            
            logger.info("File cleanup completed")
        
        except Exception as e:
            logger.error(f"Error in file cleanup: {e}")

    async def _update_learning_data(self):
        """Update learning data and topic weights"""
        try:
            logger.info("Updating learning data")
            
            # Generate performance report
            report = await self.learning_engine.generate_performance_report(days_back=7)
            
            # Log insights
            if "keyword_insights" in report:
                top_keywords = report["keyword_insights"].get("top_performing", [])
                if top_keywords:
                    logger.info(f"Top performing keywords: {[k['keyword'] for k in top_keywords[:3]]}")
            
            logger.info("Learning data update completed")
        
        except Exception as e:
            logger.error(f"Error updating learning data: {e}")

    async def _reset_daily_counts(self):
        """Reset daily run counts"""
        today = datetime.now().date()
        yesterday = today - timedelta(days=1)
        
        # Remove old counts
        if yesterday in self.daily_run_counts:
            del self.daily_run_counts[yesterday]
        
        logger.info("Daily run counts reset")

    async def schedule_one_time_run(
        self, 
        channel_name: str, 
        delay_minutes: int = 0
    ) -> str:
        """Schedule a one-time pipeline run"""
        try:
            run_time = datetime.now() + timedelta(minutes=delay_minutes)
            job_id = f"onetime_{channel_name}_{int(run_time.timestamp())}"
            
            self.scheduler.add_job(
                self._run_scheduled_pipeline,
                DateTrigger(run_date=run_time),
                args=[channel_name],
                id=job_id,
                name=f"One-time run for {channel_name}",
                replace_existing=True
            )
            
            logger.info(f"Scheduled one-time run for {channel_name} at {run_time}")
            return job_id
        
        except Exception as e:
            logger.error(f"Error scheduling one-time run: {e}")
            return ""

    async def modify_channel_schedule(
        self, 
        channel_name: str, 
        new_time: str,
        enabled: bool = True
    ) -> bool:
        """Modify the schedule for a channel"""
        try:
            job_id = f"daily_{channel_name}"
            
            if enabled:
                hour, minute = map(int, new_time.split(":"))
                
                self.scheduler.add_job(
                    self._run_scheduled_pipeline,
                    CronTrigger(hour=hour, minute=minute),
                    args=[channel_name],
                    id=job_id,
                    name=f"Daily video generation for {channel_name}",
                    replace_existing=True
                )
                
                logger.info(f"Updated schedule for {channel_name} to {new_time}")
            else:
                # Remove the job
                self.scheduler.remove_job(job_id)
                logger.info(f"Disabled schedule for {channel_name}")
            
            return True
        
        except Exception as e:
            logger.error(f"Error modifying schedule for {channel_name}: {e}")
            return False

    def get_scheduled_jobs(self) -> List[Dict]:
        """Get list of all scheduled jobs"""
        jobs = []
        
        for job in self.scheduler.get_jobs():
            next_run = job.next_run_time
            
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": next_run.isoformat() if next_run else None,
                "trigger": str(job.trigger),
                "args": job.args if hasattr(job, 'args') else []
            })
        
        return jobs

    def get_daily_stats(self) -> Dict:
        """Get daily run statistics"""
        today = datetime.now().date()
        
        return {
            "today": today.isoformat(),
            "runs_today": self.daily_run_counts.get(today, 0),
            "max_daily_runs": self.max_daily_runs,
            "runs_remaining": max(0, self.max_daily_runs - self.daily_run_counts.get(today, 0))
        }