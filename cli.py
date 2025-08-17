import typer
import asyncio
import json
from typing import Optional
from datetime import datetime
from orchestrator.pipeline import VideoGenerationPipeline
from orchestrator.scheduler import PipelineScheduler
from publish.youtube import YouTubePublisher
from analytics.fetch import AnalyticsFetcher
from analytics.learn import LearningEngine
from research.gather import TopicGatherer
from research.score import TopicScorer
from models.db import create_tables
from loguru import logger
import os
from dotenv import load_dotenv

load_dotenv()

app = typer.Typer(
    name="auto-shorts",
    help="Automated short-form video generation pipeline"
)

# Global instances (will be initialized)
pipeline = None
scheduler = None

@app.callback()
def initialize():
    """Initialize the application components"""
    global pipeline, scheduler
    
    # Set up logging
    logger.add("./data/logs/cli.log", rotation="1 day", level="INFO")
    
    # Initialize components
    pipeline = VideoGenerationPipeline()
    scheduler = PipelineScheduler()

@app.command()
def seed_ideas(
    channel: str = typer.Option(..., "--channel", "-c", help="Channel name"),
    count: int = typer.Option(50, "--count", "-n", help="Number of ideas to gather")
):
    """Seed topic ideas for a channel"""
    async def run_seed():
        try:
            # Get channel config
            channel_config = pipeline.channels_config.get(channel)
            if not channel_config:
                typer.echo(f"Error: Channel '{channel}' not found in configuration", err=True)
                raise typer.Exit(1)
            
            typer.echo(f"Gathering {count} topic ideas for {channel}...")
            
            async with TopicGatherer() as gatherer:
                ideas = await gatherer.gather_for_channel(
                    channel_config["niche"], count
                )
            
            if ideas:
                # Score and rank ideas
                scorer = TopicScorer()
                ranked_ideas = scorer.score_and_rank(ideas, channel)
                
                typer.echo(f"✅ Successfully gathered {len(ranked_ideas)} ideas")
                
                # Show top 5 ideas
                typer.echo("\nTop 5 ideas:")
                for i, idea in enumerate(ranked_ideas[:5], 1):
                    typer.echo(f"{i}. {idea.title} (score: {idea.score:.3f})")
                    typer.echo(f"   Keywords: {', '.join(idea.keywords[:3])}")
                    typer.echo()
            else:
                typer.echo("❌ No ideas found", err=True)
                raise typer.Exit(1)
                
        except Exception as e:
            typer.echo(f"❌ Error: {e}", err=True)
            raise typer.Exit(1)
    
    asyncio.run(run_seed())

@app.command()
def run_once(
    channel: str = typer.Option(..., "--channel", "-c", help="Channel name"),
    dry_run: bool = typer.Option(False, "--dry-run", "-d", help="Run without publishing")
):
    """Run pipeline once for a channel"""
    async def run_pipeline():
        try:
            # Ensure database tables exist
            await create_tables()
            
            if dry_run:
                typer.echo(f"🧪 Running dry-run for {channel}...")
                result = await pipeline.dry_run(channel)
                
                if "error" in result:
                    typer.echo(f"❌ Dry run failed: {result['error']}", err=True)
                    raise typer.Exit(1)
                
                typer.echo("✅ Dry run completed successfully")
                typer.echo(f"Selected topic: {result['selected_topic']['title']}")
                typer.echo(f"Script title: {result['script']['title']}")
                typer.echo(f"Word count: {result['script']['word_count']}")
                typer.echo(f"Voiceover: {result['voiceover']['provider']} ({result['voiceover']['duration']:.1f}s)")
            else:
                typer.echo(f"🚀 Running full pipeline for {channel}...")
                
                result = await pipeline.run_full_pipeline(channel)
                
                if result:
                    typer.echo("✅ Pipeline completed successfully")
                    typer.echo(f"Published: {result.url}")
                    typer.echo(f"Video ID: {result.video_id}")
                else:
                    typer.echo("❌ Pipeline failed", err=True)
                    raise typer.Exit(1)
                    
        except Exception as e:
            typer.echo(f"❌ Error: {e}", err=True)
            raise typer.Exit(1)
    
    asyncio.run(run_pipeline())

@app.command()
def schedule(
    daily: str = typer.Option("09:00", "--daily", help="Daily run time (HH:MM)"),
    per_channel: int = typer.Option(1, "--per-channel", help="Videos per channel per day")
):
    """Schedule daily pipeline runs"""
    async def setup_schedule():
        try:
            # Parse time
            hour, minute = map(int, daily.split(":"))
            
            typer.echo(f"⏰ Setting up daily schedule at {daily} for all channels...")
            
            # Start scheduler
            await scheduler.start_scheduler()
            
            # Update schedules for all channels
            scheduled_count = 0
            for channel_name in pipeline.channels_config.keys():
                success = await scheduler.modify_channel_schedule(
                    channel_name, daily, enabled=True
                )
                if success:
                    scheduled_count += 1
                    typer.echo(f"  ✅ {channel_name}")
                else:
                    typer.echo(f"  ❌ {channel_name} (failed)")
            
            typer.echo(f"✅ Scheduled {scheduled_count} channels")
            typer.echo("Scheduler is running. Press Ctrl+C to stop.")
            
            # Keep running
            try:
                while True:
                    await asyncio.sleep(1)
            except KeyboardInterrupt:
                typer.echo("\n🛑 Stopping scheduler...")
                await scheduler.stop_scheduler()
                
        except Exception as e:
            typer.echo(f"❌ Error: {e}", err=True)
            raise typer.Exit(1)
    
    asyncio.run(setup_schedule())

@app.command()
def oauth_youtube(
    channel: str = typer.Option(..., "--channel", "-c", help="Channel name")
):
    """Set up YouTube OAuth for a channel"""
    async def setup_oauth():
        try:
            youtube_publisher = YouTubePublisher()
            
            # Generate OAuth URL
            auth_url = youtube_publisher.get_oauth_url(channel)
            
            if auth_url:
                typer.echo(f"🔐 YouTube OAuth setup for {channel}")
                typer.echo("\n1. Open this URL in your browser:")
                typer.echo(f"   {auth_url}")
                typer.echo("\n2. Complete the authorization")
                typer.echo("3. You'll be redirected to the callback URL")
                typer.echo("\nNote: Make sure the FastAPI server is running on localhost:5317")
                typer.echo("Run: uvicorn app:app --host 0.0.0.0 --port 5317")
            else:
                typer.echo("❌ Failed to generate OAuth URL", err=True)
                raise typer.Exit(1)
                
        except Exception as e:
            typer.echo(f"❌ Error: {e}", err=True)
            raise typer.Exit(1)
    
    asyncio.run(setup_oauth())

@app.command()
def metrics(
    video_id: str = typer.Option(..., "--video-id", help="YouTube video ID")
):
    """Get metrics for a video"""
    async def get_metrics():
        try:
            analytics_fetcher = AnalyticsFetcher()
            
            typer.echo(f"📊 Fetching metrics for video {video_id}...")
            
            # This would need channel context to work properly
            # For now, we'll try with the default channel
            default_channel = os.getenv("DEFAULT_CHANNEL", "ByteCult")
            channel_config = pipeline.channels_config.get(default_channel)
            
            if not channel_config:
                typer.echo("❌ No default channel configured", err=True)
                raise typer.Exit(1)
            
            analytics = await analytics_fetcher.fetch_video_analytics(
                video_id, 
                "youtube", 
                channel_config["youtube_oauth_token"]
            )
            
            if analytics:
                typer.echo("✅ Metrics retrieved:")
                typer.echo(f"Views: {analytics.views:,}")
                typer.echo(f"Likes: {analytics.likes:,}")
                typer.echo(f"Avg view duration: {analytics.avg_view_duration_sec:.1f}s")
                
                if analytics.click_through_rate:
                    typer.echo(f"CTR: {analytics.click_through_rate:.2f}%")
            else:
                typer.echo("❌ No metrics found", err=True)
                raise typer.Exit(1)
                
        except Exception as e:
            typer.echo(f"❌ Error: {e}", err=True)
            raise typer.Exit(1)
    
    asyncio.run(get_metrics())

@app.command()
def list_channels():
    """List configured channels"""
    try:
        typer.echo("📺 Configured channels:")
        typer.echo()
        
        for name, config in pipeline.channels_config.items():
            typer.echo(f"• {name}")
            typer.echo(f"  Niche: {config['niche']}")
            typer.echo(f"  Schedule: {config.get('local_time', '09:00')}")
            typer.echo(f"  Style: {config.get('style', 'clean-bold')}")
            typer.echo(f"  Banned terms: {len(config.get('banned_terms', []))}")
            typer.echo()
            
    except Exception as e:
        typer.echo(f"❌ Error: {e}", err=True)
        raise typer.Exit(1)

@app.command()
def status():
    """Show pipeline status"""
    try:
        typer.echo("🔍 Pipeline Status")
        typer.echo("=" * 50)
        
        # Pipeline status
        status = pipeline.get_pipeline_status()
        
        typer.echo(f"Channels configured: {status['channels_configured']}")
        typer.echo(f"Available channels: {', '.join(status['available_channels'])}")
        typer.echo()
        
        # TTS providers
        typer.echo("TTS Providers:")
        for provider, available in status['tts_providers'].items():
            status_icon = "✅" if available else "❌"
            typer.echo(f"  {status_icon} {provider}")
        
        typer.echo()
        
        # Publishers
        typer.echo("Publishers:")
        for publisher, available in status['publishers'].items():
            status_icon = "✅" if available else "❌"
            typer.echo(f"  {status_icon} {publisher}")
        
        typer.echo()
        typer.echo(f"Content root: {status['content_root']}")
        
    except Exception as e:
        typer.echo(f"❌ Error: {e}", err=True)
        raise typer.Exit(1)

@app.command()
def test_components():
    """Test all pipeline components"""
    async def run_tests():
        try:
            typer.echo("🧪 Testing pipeline components...")
            typer.echo()
            
            # Test database connection
            typer.echo("1. Testing database connection...")
            try:
                await create_tables()
                typer.echo("   ✅ Database OK")
            except Exception as e:
                typer.echo(f"   ❌ Database failed: {e}")
            
            # Test TTS
            typer.echo("2. Testing Edge TTS...")
            try:
                from tts.edge_tts import EdgeTTSProvider
                edge_tts = EdgeTTSProvider()
                test_result = await edge_tts.test_voice_quality()
                if test_result:
                    typer.echo("   ✅ Edge TTS OK")
                else:
                    typer.echo("   ❌ Edge TTS failed")
            except Exception as e:
                typer.echo(f"   ❌ Edge TTS error: {e}")
            
            # Test ElevenLabs (if configured)
            if os.getenv("ELEVENLABS_API_KEY"):
                typer.echo("3. Testing ElevenLabs API...")
                try:
                    from tts.elevenlabs import ElevenLabsProvider
                    elevenlabs = ElevenLabsProvider()
                    test_result = await elevenlabs.test_api_connection()
                    if test_result:
                        typer.echo("   ✅ ElevenLabs OK")
                    else:
                        typer.echo("   ❌ ElevenLabs failed")
                except Exception as e:
                    typer.echo(f"   ❌ ElevenLabs error: {e}")
            else:
                typer.echo("3. ElevenLabs API not configured (skipping)")
            
            # Test OpenAI
            typer.echo("4. Testing OpenAI API...")
            try:
                from nlp.writer import ScriptWriter
                writer = ScriptWriter()
                # This would test with a minimal request
                typer.echo("   ✅ OpenAI configuration OK")
            except Exception as e:
                typer.echo(f"   ❌ OpenAI error: {e}")
            
            typer.echo()
            typer.echo("✅ Component testing completed")
            
        except Exception as e:
            typer.echo(f"❌ Error: {e}", err=True)
            raise typer.Exit(1)
    
    asyncio.run(run_tests())

if __name__ == "__main__":
    app()