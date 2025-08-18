import asyncio
import uuid
from typing import Optional, Dict, List
from datetime import datetime
from models.schemas import (
    TopicIdea, ScriptPackage, Voiceover, AssetBundle,
    RenderSpec, RenderResult, PublishResult, PipelineJob
)
from research.gather import TopicGatherer
from research.score import TopicScorer
from nlp.writer import ScriptWriter
from tts.edge_tts import EdgeTTSProvider
from tts.elevenlabs import ElevenLabsProvider
from assets.broll import BRollProvider
from assets.captions import CaptionGenerator
from video.compose import VideoComposer
from publish.youtube import YouTubePublisher
from publish.tiktok import TikTokPublisher
from analytics.learn import LearningEngine
from models.db import get_db, PipelineJobDB, TopicIdeaDB, ScriptPackageDB
from loguru import logger
import os
import json
from dotenv import load_dotenv

load_dotenv()

class VideoGenerationPipeline:
    def __init__(self):
        self.content_root = os.getenv("CONTENT_ROOT", "./data")
        self.channels_config = self._load_channels_config()

        # Initialize components
        self.topic_gatherer = None
        self.topic_scorer = TopicScorer(self.content_root)
        self.script_writer = ScriptWriter()

        # TTS providers
        self.edge_tts = EdgeTTSProvider()
        self.elevenlabs_tts = ElevenLabsProvider()

        # Asset providers
        self.broll_provider = BRollProvider()
        self.caption_generator = CaptionGenerator()

        # Video composition
        self.video_composer = VideoComposer()

        # Publishers
        self.youtube_publisher = YouTubePublisher()
        self.tiktok_publisher = TikTokPublisher()

        # Learning engine
        self.learning_engine = LearningEngine(self.content_root)

    def _load_channels_config(self) -> Dict:
        """Load channels configuration"""
        try:
            channels_path = os.getenv("CHANNELS_JSON", "./config/channels.json")
            with open(channels_path, 'r') as f:
                channels_list = json.load(f)
            # Convert to dict for easier access
            return {channel['name']: channel for channel in channels_list}
        except Exception as e:
            logger.error(f"Error loading channels config: {e}")
            return {}

    async def run_full_pipeline(
        self,
        channel_name: str,
        topic_count: int = 30,
        retry_attempts: int = 3
    ) -> Optional[PublishResult]:
        """Run the complete video generation pipeline"""
        job_id = str(uuid.uuid4())

        try:
            # Create pipeline job record
            job = await self._create_pipeline_job(job_id, channel_name)
            logger.info(f"Starting pipeline for channel {channel_name} (job: {job_id})")

            # Get channel configuration
            channel_config = self.channels_config.get(channel_name)
            if not channel_config:
                raise ValueError(f"Channel {channel_name} not found in configuration")

            # Step 1: Research and gather topics
            logger.info("Step 1: Researching trending topics...")
            ideas = await self._research_topics(channel_config, topic_count)

            if not ideas:
                raise Exception("No suitable topic ideas found")

            # Step 2: Select and score topics (pick safely)
            logger.info("Step 2: Selecting top topic...")
            best_idea = next((i for i in ideas if i is not None), None)
            if not best_idea:
                raise Exception("No usable topic after scoring/fallback")
            await self._update_job_topic(job_id, getattr(best_idea, "id", None))

            # Step 3: Generate script
            logger.info("Step 3: Generating script...")
            script_package = await self._generate_script(
                best_idea, channel_config, retry_attempts
            )
            if not script_package:
                raise Exception("Failed to generate suitable script")

            # Step 4: Generate voiceover
            logger.info("Step 4: Generating voiceover...")
            voiceover = await self._generate_voiceover(
                script_package, channel_config
            )
            if not voiceover:
                raise Exception("Failed to generate voiceover")

            # Step 5: Gather assets
            logger.info("Step 5: Gathering B-roll and assets...")
            assets = await self._gather_assets(
                best_idea, script_package, voiceover
            )

            # Step 6: Compose video
            logger.info("Step 6: Composing final video...")
            render_spec = RenderSpec(style=channel_config.get("style", "clean-bold"))
            render_result = await self._compose_video(
                voiceover, assets, render_spec, script_package
            )
            if not render_result:
                raise Exception("Failed to compose video")

            # Step 7: Publish video
            logger.info("Step 7: Publishing to platforms...")
            publish_result = await self._publish_video(
                render_result, script_package, channel_config
            )
            if not publish_result:
                raise Exception("Failed to publish video")

            # Step 8: Schedule analytics collection
            logger.info("Step 8: Scheduling analytics collection...")
            await self._schedule_analytics(publish_result.video_id, best_idea, channel_name)

            # Update job as completed
            await self._complete_pipeline_job(job_id, publish_result.video_id)

            logger.info(f"Pipeline completed successfully: {publish_result.url}")
            return publish_result

        except Exception as e:
            logger.error(f"Pipeline failed for {channel_name}: {e}")
            try:
                await self._fail_pipeline_job(job_id, str(e))
            except Exception as inner:
                logger.error(f"Failed to record pipeline failure: {inner}")
            return None

    async def _create_pipeline_job(self, job_id: str, channel: str) -> PipelineJob:
        """Create pipeline job record"""
        async for db in get_db():
            job_db = PipelineJobDB(
                id=job_id,
                channel=channel,
                status="running",
                started_at=datetime.now()
            )
            db.add(job_db)
            await db.commit()

            return PipelineJob(
                id=job_id,
                channel=channel,
                status="running",
                started_at=datetime.now()
            )

    async def _update_job_topic(self, job_id: str, topic_id: Optional[str]):
        """Update job with selected topic"""
        if not topic_id:
            return
        async for db in get_db():
            from sqlalchemy import update
            stmt = update(PipelineJobDB).where(
                PipelineJobDB.id == job_id
            ).values(topic_id=topic_id)
            await db.execute(stmt)
            await db.commit()

    async def _complete_pipeline_job(self, job_id: str, video_id: Optional[str]):
        """Mark pipeline job as completed"""
        async for db in get_db():
            from sqlalchemy import update
            stmt = update(PipelineJobDB).where(
                PipelineJobDB.id == job_id
            ).values(
                status="success",
                video_id=video_id,
                completed_at=datetime.now()
            )
            await db.execute(stmt)
            await db.commit()

    async def _fail_pipeline_job(self, job_id: str, error_message: str):
        """Mark pipeline job as failed"""
        async for db in get_db():
            from sqlalchemy import update
            stmt = update(PipelineJobDB).where(
                PipelineJobDB.id == job_id
            ).values(
                status="failed",
                error_message=error_message,
                completed_at=datetime.now()
            )
            await db.execute(stmt)
            await db.commit()

    async def _research_topics(self, channel_config: Dict, count: int) -> List[TopicIdea]:
        """Research and score topics for the channel (robust fallback)."""
        async with TopicGatherer() as gatherer:
            raw_ideas = await gatherer.gather_for_channel(
                channel_config.get("niche", ""), count
            ) or []

        if not raw_ideas:
            return []

        # Score and rank ideas (fallback to raw if scorer returns empty/None)
        try:
            ranked = self.topic_scorer.score_and_rank(
                raw_ideas, channel_config.get("name", "")
            ) or []
        except Exception as e:
            logger.warning(f"Scoring failed, using raw ideas: {e}")
            ranked = []

        ideas = ranked if ranked else raw_ideas

        # Store top ideas in database (defensive field access)
        try:
            async for db in get_db():
                for idea in ideas[:10]:
                    db_idea = TopicIdeaDB(
                        id=getattr(idea, "id", str(uuid.uuid4())),
                        seed_source=getattr(getattr(idea, "seed_source", None), "value", "unknown"),
                        title=getattr(idea, "title", ""),
                        angle=getattr(idea, "angle", ""),
                        keywords=getattr(idea, "keywords", []),
                        score=float(getattr(idea, "score", 0.0) or 0.0),
                        channel=channel_config.get("name", ""),
                        created_at=getattr(idea, "created_at", datetime.now()),
                        used=False
                    )
                    db.add(db_idea)
                await db.commit()
        except Exception as e:
            logger.warning(f"Failed to persist topic ideas (non-fatal): {e}")

        return ideas

    async def _generate_script(
        self,
        idea: TopicIdea,
        channel_config: Dict,
        max_retries: int
    ) -> Optional[ScriptPackage]:
        """Generate script with retries"""
        for attempt in range(max_retries):
            try:
                script_package = await self.script_writer.create_script_package(
                    idea,
                    channel_config.get("niche", ""),
                    channel_config.get("banned_terms", [])
                )
                if script_package:
                    # Store in database
                    try:
                        async for db in get_db():
                            db_script = ScriptPackageDB(
                                id=str(uuid.uuid4()),
                                topic_id=getattr(script_package, "topic_id", getattr(idea, "id", "")),
                                hook=script_package.hook,
                                script_text=script_package.script_text,
                                word_count=int(getattr(script_package, "word_count", 0) or 0),
                                title=script_package.title,
                                description=script_package.description,
                                hashtags=script_package.hashtags,
                                created_at=script_package.created_at
                            )
                            db.add(db_script)
                            await db.commit()
                    except Exception as e:
                        logger.warning(f"Failed to persist script package (non-fatal): {e}")
                    return script_package
                logger.warning(f"Script generation attempt {attempt + 1} failed")
            except Exception as e:
                logger.error(f"Script generation error (attempt {attempt + 1}): {e}")
        return None

    async def _generate_voiceover(
        self,
        script_package: ScriptPackage,
        channel_config: Dict
    ) -> Optional[Voiceover]:
        """Generate voiceover with fallback providers"""
        # Try ElevenLabs first if API key is available
        if os.getenv("ELEVENLABS_API_KEY"):
            try:
                _ = self.elevenlabs_tts.get_voice_for_niche(channel_config.get("niche", ""))
                voiceover = await self.elevenlabs_tts.generate_voiceover(
                    script_package.script_text,
                    voice_settings={
                        "stability": 0.7,
                        "similarity_boost": 0.8,
                        "style": 0.6
                    }
                )
                if voiceover:
                    return voiceover
            except Exception as e:
                logger.warning(f"ElevenLabs TTS failed, falling back to Edge TTS: {e}")

        # Fallback to Edge TTS
        try:
            voice = self.edge_tts.get_voice_for_niche(channel_config.get("niche", ""))
            self.edge_tts.voice = voice
            ssml_script = self.edge_tts.create_emphasized_ssml(
                script_package.script_text,
                script_package.hook
            )
            voiceover = await self.edge_tts.generate_with_ssml(ssml_script)
            return voiceover
        except Exception as e:
            logger.error(f"All TTS providers failed: {e}")
            return None

    async def _gather_assets(
        self,
        idea: TopicIdea,
        script_package: ScriptPackage,
        voiceover: Voiceover
    ) -> AssetBundle:
        """Gather B-roll clips and generate captions"""
        # Get enhanced keywords from script for better visual matching
        try:
            script_keywords = self.broll_provider.get_topic_keywords_from_script(
                script_package.script_text
            ) or []
        except Exception:
            script_keywords = []
        idea_keywords = getattr(idea, "keywords", []) or []
        combined_keywords = list({*(idea_keywords), *script_keywords})

        # Get B-roll clips and stock images
        video_clips = await self.broll_provider.fetch_broll_clips(
            combined_keywords,
            script_package.title,
            count=6,
            duration_range=(6, 12)
        )

        # Generate captions
        srt_path = self.caption_generator.create_hook_highlight_srt(
            script_package.script_text,
            script_package.hook,
            voiceover
        )

        # Add royalty-free background music
        music_path = await self._get_background_music(script_package.title)

        return AssetBundle(
            video_clips=video_clips,
            music_path=music_path,
            srt_path=srt_path
        )

    async def _get_background_music(self, title: str) -> Optional[str]:
        """
        Placeholder: return a path to background music or None.
        Implement your selection logic here if/when needed.
        """
        return None

    async def _compose_video(
        self,
        voiceover: Voiceover,
        assets: AssetBundle,
        render_spec: RenderSpec,
        script_package: ScriptPackage
    ) -> Optional[RenderResult]:
        """Compose the final video"""
        try:
            render_result = await self.video_composer.compose_video(
                voiceover, assets, render_spec, script_package
            )
            # Clean up temp files
            self.video_composer.cleanup_temp_files()
            return render_result
        except Exception as e:
            logger.error(f"Video composition failed: {e}")
            return None

    async def _publish_video(
        self,
        render_result: RenderResult,
        script_package: ScriptPackage,
        channel_config: Dict
    ) -> Optional[PublishResult]:
        """Publish video to configured platforms"""
        try:
            # YouTube is primary platform
            publish_result = await self.youtube_publisher.upload_video(
                video_path=render_result.path,
                title=script_package.title,
                description=script_package.description,
                tags=[tag.strip('#') for tag in (script_package.hashtags or [])],
                channel_token_path=channel_config["youtube_oauth_token"],
                thumbnail_path=getattr(render_result, "thumb_path", None)
            )
            if not publish_result:
                raise Exception("YouTube upload failed")

            # Optional: Also publish to TikTok if enabled
            if os.getenv("ENABLE_TIKTOK", "false").lower() == "true":
                try:
                    tiktok_result = await self.tiktok_publisher.upload_video(
                        render_result.path,
                        script_package.title,
                        script_package.hashtags,
                        channel_config["name"]
                    )
                    if tiktok_result:
                        logger.info(f"Also published to TikTok: {tiktok_result.url}")
                except Exception as e:
                    logger.warning(f"TikTok upload failed: {e}")

            return publish_result
        except Exception as e:
            logger.error(f"Publishing failed: {e}")
            return None

    async def _schedule_analytics(
        self,
        video_id: str,
        idea: TopicIdea,
        channel_name: str
    ):
        """Schedule analytics collection for 24 hours later"""
        # This would integrate with APScheduler
        # For now, we'll just mark the topic as used
        try:
            self.topic_scorer.mark_topic_used(
                getattr(idea, "id", None),
                getattr(idea, "keywords", []),
                channel_name
            )
        except Exception as e:
            logger.warning(f"Failed to mark topic used (non-fatal): {e}")
        logger.info(f"Analytics collection scheduled for video {video_id}")

    async def dry_run(self, channel_name: str) -> Dict:
        """Run pipeline in dry mode (no publishing) with robust error handling."""
        try:
            logger.info(f"Starting dry run for channel {channel_name}")

            # Load channel config
            channel_config = self.channels_config.get(channel_name)
            if not channel_config:
                return {"error": f"Channel '{channel_name}' not found in configuration"}

            niche = channel_config.get("niche", "").strip()
            banned_terms = channel_config.get("banned_terms", [])

            # Gather ideas with timeout
            try:
                async with asyncio.timeout(30):
                    async with TopicGatherer() as gatherer:
                        ideas = await gatherer.gather_for_channel(niche, 10)
            except asyncio.TimeoutError:
                return {"error": "Topic gathering timed out"}
            except Exception as e:
                logger.error(f"Topic gathering failed: {e}")
                return {"error": f"Topic gathering failed: {str(e)}"}

            if not ideas:
                return {"error": f"No topics found for channel '{channel_name}'"}

            # Score ideas with fallback
            try:
                ranked_ideas = self.topic_scorer.score_and_rank(ideas, channel_name) or ideas
            except Exception as e:
                logger.warning(f"Scoring failed, using raw ideas: {e}")
                ranked_ideas = ideas

            if not ranked_ideas:
                return {"error": "No usable topics after scoring"}

            # Try multiple ideas until one works
            MAX_ATTEMPTS = 3
            result = None

            for i, idea in enumerate(ranked_ideas[:MAX_ATTEMPTS]):
                try:
                    logger.info(f"Trying idea {i+1}/{MAX_ATTEMPTS}: {getattr(idea, 'title', '')}")

                    # Generate script
                    script_package = await self.script_writer.create_script_package(
                        idea, niche, banned_terms
                    )
                    if not script_package:
                        logger.warning(f"Script generation failed for idea {i+1}")
                        continue

                    # Generate sample voiceover
                    voiceover = None
                    test_text = script_package.hook or script_package.title or ""
                    if test_text:
                        try:
                            voiceover = await self.edge_tts.generate_voiceover(test_text)
                        except Exception as e:
                            logger.warning(f"Voiceover failed for idea {i+1}: {e}")

                    # Build result
                    result = {
                        "channel": channel_name,
                        "selected_topic": {
                            "title": getattr(idea, "title", ""),
                            "score": getattr(idea, "score", 0.0),
                            "keywords": getattr(idea, "keywords", []),
                        },
                        "script": {
                            "title": script_package.title,
                            "hook": script_package.hook,
                            "word_count": script_package.word_count,
                            "hashtags": script_package.hashtags,
                        },
                        "voiceover": {
                            "generated": bool(voiceover),
                            "duration": getattr(voiceover, "duration_sec", 0.0),
                            "provider": getattr(voiceover, "provider", None),
                        },
                        "status": "dry_run_complete",
                    }

                    # Cleanup
                    try:
                        if voiceover and getattr(voiceover, "path", None):
                            os.remove(voiceover.path)
                    except Exception:
                        pass

                    break  # success

                except Exception as e:
                    logger.warning(f"Attempt {i+1} failed: {e}")
                    continue

            if not result:
                return {"error": f"Failed after {MAX_ATTEMPTS} attempts."}

            return result

        except Exception as e:
            logger.error(f"Dry run failed: {e}")
            return {"error": str(e)}

    def get_pipeline_status(self) -> Dict:
        """Get current pipeline status"""
        return {
            "channels_configured": len(self.channels_config),
            "available_channels": list(self.channels_config.keys()),
            "tts_providers": {
                "edge_tts": True,
                "elevenlabs": bool(os.getenv("ELEVENLABS_API_KEY"))
            },
            "publishers": {
                "youtube": bool(os.getenv("YOUTUBE_CLIENT_ID")),
                "tiktok": os.getenv("ENABLE_TIKTOK", "false").lower() == "true"
            },
            "content_root": self.content_root
        }
