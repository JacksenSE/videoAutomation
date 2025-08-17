from sqlalchemy import create_engine, Column, String, Float, Integer, Boolean, DateTime, Text, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/db.sqlite3")

Base = declarative_base()

class TopicIdeaDB(Base):
    __tablename__ = "topic_ideas"
    
    id = Column(String, primary_key=True)
    seed_source = Column(String, nullable=False)
    title = Column(String, nullable=False)
    angle = Column(String, nullable=False)
    keywords = Column(JSON, nullable=False)
    score = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    used = Column(Boolean, default=False)
    channel = Column(String, nullable=False)

class ScriptPackageDB(Base):
    __tablename__ = "script_packages"
    
    id = Column(String, primary_key=True)
    topic_id = Column(String, nullable=False)
    hook = Column(Text, nullable=False)
    script_text = Column(Text, nullable=False)
    word_count = Column(Integer, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    hashtags = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.now)

class PipelineJobDB(Base):
    __tablename__ = "pipeline_jobs"
    
    id = Column(String, primary_key=True)
    channel = Column(String, nullable=False)
    status = Column(String, nullable=False)
    topic_id = Column(String)
    video_id = Column(String)
    error_message = Column(Text)
    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime)
    retry_count = Column(Integer, default=0)

class AnalyticsDB(Base):
    __tablename__ = "analytics"
    
    video_id = Column(String, primary_key=True)
    views = Column(Integer, nullable=False)
    likes = Column(Integer, nullable=False)
    avg_view_duration_sec = Column(Float, nullable=False)
    click_through_rate = Column(Float)
    audience_retention = Column(JSON)
    fetched_at = Column(DateTime, default=datetime.now)

# Async engine and session
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)