from pydantic import BaseModel, Field, HttpUrl
from typing import List, Optional, Dict
from datetime import datetime
from enum import Enum

class TopicSource(str, Enum):
    YT_TRENDING = "yt_trending"
    RSS = "rss"
    REDDIT = "reddit"
    USER = "user"

class TopicIdea(BaseModel):
    id: str
    seed_source: TopicSource
    title: str
    angle: str
    keywords: List[str]
    score: float = Field(ge=0, le=1)
    created_at: datetime = Field(default_factory=datetime.now)
    used: bool = False

class ScriptPackage(BaseModel):
    topic_id: str
    hook: str
    script_text: str
    word_count: int
    title: str
    description: str
    hashtags: List[str]
    created_at: datetime = Field(default_factory=datetime.now)

class Voiceover(BaseModel):
    path: str
    duration_sec: float
    voice_id: str
    provider: str  # "edge-tts" or "elevenlabs"

class AssetBundle(BaseModel):
    video_clips: List[str]
    music_path: Optional[str] = None
    srt_path: Optional[str] = None
    thumbnail_path: Optional[str] = None

class RenderSpec(BaseModel):
    width: int = 1080
    height: int = 1920
    fps: int = 30
    style: str = "clean-bold"
    safe_top_px: int = 200
    safe_bottom_px: int = 200

class RenderResult(BaseModel):
    path: str
    thumb_path: Optional[str] = None
    duration_sec: float
    file_size_mb: float

class PublishResult(BaseModel):
    platform: str
    video_id: str
    url: HttpUrl
    scheduled: bool = False
    published_at: datetime = Field(default_factory=datetime.now)

class AnalyticsData(BaseModel):
    video_id: str
    views: int
    likes: int
    avg_view_duration_sec: float
    click_through_rate: Optional[float] = None
    audience_retention: Optional[Dict] = None
    fetched_at: datetime = Field(default_factory=datetime.now)

class PipelineJob(BaseModel):
    id: str
    channel: str
    status: str  # "pending", "running", "success", "failed"
    topic_id: Optional[str] = None
    video_id: Optional[str] = None
    error_message: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    retry_count: int = 0

class ChannelConfig(BaseModel):
    name: str
    youtube_oauth_token: str
    niche: str
    banned_terms: List[str]
    local_time: str = "09:00"
    style: str = "clean-bold"