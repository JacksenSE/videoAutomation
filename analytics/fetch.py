import asyncio
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from models.schemas import AnalyticsData
from publish.youtube import YouTubePublisher
from publish.tiktok import TikTokPublisher
from models.db import get_db, AnalyticsDB
from sqlalchemy import select
from loguru import logger

class AnalyticsFetcher:
    def __init__(self):
        self.youtube_publisher = YouTubePublisher()
        self.tiktok_publisher = TikTokPublisher()

    async def fetch_video_analytics(
        self, 
        video_id: str, 
        platform: str, 
        channel_token_path: str
    ) -> Optional[AnalyticsData]:
        """Fetch analytics for a specific video"""
        try:
            if platform == "youtube":
                return await self.youtube_publisher.get_video_analytics(
                    video_id, channel_token_path
                )
            elif platform == "tiktok":
                # TikTok analytics are limited without official API
                tiktok_data = await self.tiktok_publisher.get_video_analytics(video_id)
                if tiktok_data:
                    return AnalyticsData(
                        video_id=video_id,
                        views=tiktok_data.get("views", 0),
                        likes=tiktok_data.get("likes", 0),
                        avg_view_duration_sec=0.0,  # Not available
                        click_through_rate=None,
                        audience_retention=None
                    )
            
            logger.warning(f"Unsupported platform for analytics: {platform}")
            return None
            
        except Exception as e:
            logger.error(f"Error fetching analytics for {video_id}: {e}")
            return None

    async def fetch_and_store_analytics(
        self, 
        video_id: str, 
        platform: str, 
        channel_token_path: str
    ) -> bool:
        """Fetch analytics and store in database"""
        try:
            analytics = await self.fetch_video_analytics(
                video_id, platform, channel_token_path
            )
            
            if not analytics:
                return False
            
            # Store in database
            async for db in get_db():
                # Check if analytics already exist
                stmt = select(AnalyticsDB).where(AnalyticsDB.video_id == video_id)
                result = await db.execute(stmt)
                existing = result.scalar_one_or_none()
                
                if existing:
                    # Update existing record
                    existing.views = analytics.views
                    existing.likes = analytics.likes
                    existing.avg_view_duration_sec = analytics.avg_view_duration_sec
                    existing.click_through_rate = analytics.click_through_rate
                    existing.audience_retention = analytics.audience_retention
                    existing.fetched_at = datetime.now()
                else:
                    # Create new record
                    db_analytics = AnalyticsDB(
                        video_id=analytics.video_id,
                        views=analytics.views,
                        likes=analytics.likes,
                        avg_view_duration_sec=analytics.avg_view_duration_sec,
                        click_through_rate=analytics.click_through_rate,
                        audience_retention=analytics.audience_retention,
                        fetched_at=analytics.fetched_at
                    )
                    db.add(db_analytics)
                
                await db.commit()
                logger.info(f"Stored analytics for video {video_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error storing analytics for {video_id}: {e}")
            return False

    async def fetch_analytics_for_channel(
        self, 
        channel_name: str,
        days_back: int = 7
    ) -> List[AnalyticsData]:
        """Fetch analytics for all recent videos from a channel"""
        analytics_list = []
        
        try:
            async for db in get_db():
                # Get videos from last N days
                cutoff_date = datetime.now() - timedelta(days=days_back)
                
                stmt = select(AnalyticsDB).where(
                    AnalyticsDB.fetched_at >= cutoff_date
                ).order_by(AnalyticsDB.fetched_at.desc())
                
                result = await db.execute(stmt)
                db_analytics = result.scalars().all()
                
                for db_item in db_analytics:
                    analytics = AnalyticsData(
                        video_id=db_item.video_id,
                        views=db_item.views,
                        likes=db_item.likes,
                        avg_view_duration_sec=db_item.avg_view_duration_sec,
                        click_through_rate=db_item.click_through_rate,
                        audience_retention=db_item.audience_retention,
                        fetched_at=db_item.fetched_at
                    )
                    analytics_list.append(analytics)
                
        except Exception as e:
            logger.error(f"Error fetching channel analytics: {e}")
        
        return analytics_list

    async def calculate_performance_metrics(
        self, 
        video_id: str
    ) -> Dict:
        """Calculate derived performance metrics"""
        try:
            async for db in get_db():
                stmt = select(AnalyticsDB).where(AnalyticsDB.video_id == video_id)
                result = await db.execute(stmt)
                analytics = result.scalar_one_or_none()
                
                if not analytics:
                    return {}
                
                metrics = {
                    "video_id": video_id,
                    "views": analytics.views,
                    "likes": analytics.likes,
                    "avg_view_duration": analytics.avg_view_duration_sec,
                }
                
                # Calculate derived metrics
                if analytics.views > 0:
                    metrics["engagement_rate"] = (analytics.likes / analytics.views) * 100
                else:
                    metrics["engagement_rate"] = 0
                
                # Performance category based on views
                if analytics.views >= 10000:
                    metrics["performance_category"] = "viral"
                elif analytics.views >= 5000:
                    metrics["performance_category"] = "high"
                elif analytics.views >= 1000:
                    metrics["performance_category"] = "good"
                elif analytics.views >= 100:
                    metrics["performance_category"] = "average"
                else:
                    metrics["performance_category"] = "low"
                
                # Retention assessment
                if analytics.avg_view_duration_sec > 0:
                    # Assume average video is 30 seconds for Shorts
                    estimated_video_duration = 30
                    retention_rate = (analytics.avg_view_duration_sec / estimated_video_duration) * 100
                    metrics["retention_rate"] = min(100, retention_rate)
                    
                    if retention_rate >= 70:
                        metrics["retention_category"] = "excellent"
                    elif retention_rate >= 50:
                        metrics["retention_category"] = "good"
                    elif retention_rate >= 30:
                        metrics["retention_category"] = "fair"
                    else:
                        metrics["retention_category"] = "poor"
                else:
                    metrics["retention_rate"] = 0
                    metrics["retention_category"] = "unknown"
                
                return metrics
                
        except Exception as e:
            logger.error(f"Error calculating performance metrics: {e}")
            return {}

    async def get_channel_performance_summary(
        self, 
        channel_name: str,
        days_back: int = 30
    ) -> Dict:
        """Get overall performance summary for a channel"""
        try:
            analytics_list = await self.fetch_analytics_for_channel(channel_name, days_back)
            
            if not analytics_list:
                return {
                    "channel": channel_name,
                    "period_days": days_back,
                    "total_videos": 0,
                    "total_views": 0,
                    "total_likes": 0,
                    "avg_views_per_video": 0,
                    "avg_likes_per_video": 0,
                    "avg_engagement_rate": 0,
                    "best_performing_video": None
                }
            
            total_videos = len(analytics_list)
            total_views = sum(a.views for a in analytics_list)
            total_likes = sum(a.likes for a in analytics_list)
            
            avg_views = total_views / total_videos if total_videos > 0 else 0
            avg_likes = total_likes / total_videos if total_videos > 0 else 0
            avg_engagement = (total_likes / total_views * 100) if total_views > 0 else 0
            
            # Find best performing video
            best_video = max(analytics_list, key=lambda x: x.views) if analytics_list else None
            
            summary = {
                "channel": channel_name,
                "period_days": days_back,
                "total_videos": total_videos,
                "total_views": total_views,
                "total_likes": total_likes,
                "avg_views_per_video": round(avg_views, 1),
                "avg_likes_per_video": round(avg_likes, 1),
                "avg_engagement_rate": round(avg_engagement, 2),
                "best_performing_video": {
                    "video_id": best_video.video_id,
                    "views": best_video.views,
                    "likes": best_video.likes
                } if best_video else None
            }
            
            return summary
            
        except Exception as e:
            logger.error(f"Error generating performance summary: {e}")
            return {}

    async def schedule_analytics_collection(self, video_ids: List[str], delay_hours: int = 24):
        """Schedule analytics collection for videos after publish delay"""
        logger.info(f"Scheduled analytics collection for {len(video_ids)} videos in {delay_hours} hours")
        
        # This would integrate with APScheduler to schedule jobs
        # For now, we'll just log the intent
        for video_id in video_ids:
            logger.info(f"Will collect analytics for {video_id} at {datetime.now() + timedelta(hours=delay_hours)}")

    def analyze_trending_topics_performance(
        self, 
        analytics_list: List[AnalyticsData],
        topic_keywords: Dict[str, List[str]]
    ) -> Dict:
        """Analyze which topics/keywords perform best"""
        try:
            keyword_performance = {}
            
            for analytics in analytics_list:
                video_id = analytics.video_id
                
                # Get keywords for this video
                keywords = topic_keywords.get(video_id, [])
                
                for keyword in keywords:
                    if keyword not in keyword_performance:
                        keyword_performance[keyword] = {
                            "videos": 0,
                            "total_views": 0,
                            "total_likes": 0,
                            "avg_views": 0,
                            "avg_likes": 0
                        }
                    
                    kp = keyword_performance[keyword]
                    kp["videos"] += 1
                    kp["total_views"] += analytics.views
                    kp["total_likes"] += analytics.likes
                    kp["avg_views"] = kp["total_views"] / kp["videos"]
                    kp["avg_likes"] = kp["total_likes"] / kp["videos"]
            
            # Sort by average views
            sorted_keywords = sorted(
                keyword_performance.items(),
                key=lambda x: x[1]["avg_views"],
                reverse=True
            )
            
            return {
                "top_performing_keywords": sorted_keywords[:10],
                "total_keywords_analyzed": len(keyword_performance)
            }
            
        except Exception as e:
            logger.error(f"Error analyzing trending topics performance: {e}")
            return {}