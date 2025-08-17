import os
import asyncio
from typing import Optional
from playwright.async_api import async_playwright, Browser, Page
from models.schemas import PublishResult
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

class TikTokPublisher:
    def __init__(self):
        self.enabled = os.getenv("ENABLE_TIKTOK", "false").lower() == "true"
        if not self.enabled:
            logger.info("TikTok publishing is disabled (ENABLE_TIKTOK=false)")

    async def upload_video(
        self,
        video_path: str,
        title: str,
        hashtags: list,
        channel_name: str
    ) -> Optional[PublishResult]:
        """Upload video to TikTok using browser automation"""
        
        if not self.enabled:
            logger.warning("TikTok publishing is disabled")
            return None

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=False)  # Non-headless for manual login
                context = await browser.new_context(
                    viewport={"width": 1280, "height": 720},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                
                page = await context.new_page()
                
                # Navigate to TikTok upload page
                await page.goto("https://www.tiktok.com/upload/")
                await page.wait_for_timeout(3000)
                
                # Check if user needs to log in
                if "login" in page.url.lower() or await page.locator('button:has-text("Log in")').is_visible():
                    logger.warning("TikTok login required - manual intervention needed")
                    await page.wait_for_timeout(30000)  # Wait 30 seconds for manual login
                
                # Upload video file
                file_input = await page.wait_for_selector('input[type="file"]', timeout=10000)
                await file_input.set_input_files(video_path)
                
                # Wait for video to process
                await page.wait_for_selector('[data-testid="video-preview"]', timeout=30000)
                logger.info("Video uploaded and processed")
                
                # Add caption with hashtags
                caption_text = f"{title}\n\n" + " ".join([f"#{tag.strip('#')}" for tag in hashtags])
                caption_textarea = await page.wait_for_selector('[data-testid="caption-input"]')
                await caption_textarea.fill(caption_text)
                
                # Set privacy to public
                privacy_button = page.locator('button:has-text("Public")')
                if await privacy_button.is_visible():
                    await privacy_button.click()
                
                # Allow comments and reactions
                try:
                    allow_comments = page.locator('[data-testid="allow-comments"]')
                    if await allow_comments.is_visible() and not await allow_comments.is_checked():
                        await allow_comments.check()
                    
                    allow_reactions = page.locator('[data-testid="allow-reactions"]')  
                    if await allow_reactions.is_visible() and not await allow_reactions.is_checked():
                        await allow_reactions.check()
                except Exception as e:
                    logger.warning(f"Could not set comment/reaction settings: {e}")
                
                # Post the video
                post_button = page.locator('button[data-testid="post-button"], button:has-text("Post")')
                await post_button.wait_for(state="visible", timeout=10000)
                await post_button.click()
                
                # Wait for upload completion
                await page.wait_for_timeout(5000)
                
                # Try to get video URL from the success page
                video_url = None
                try:
                    # Look for success indicators
                    success_indicators = [
                        'text="Your video is being uploaded"',
                        'text="Video uploaded"',
                        '[data-testid="upload-success"]'
                    ]
                    
                    for indicator in success_indicators:
                        try:
                            await page.wait_for_selector(indicator, timeout=5000)
                            logger.info("TikTok upload appears successful")
                            break
                        except:
                            continue
                    
                    # Try to extract video ID or URL if available
                    current_url = page.url
                    if "tiktok.com" in current_url and "/video/" in current_url:
                        video_url = current_url
                        
                except Exception as e:
                    logger.warning(f"Could not confirm upload success: {e}")
                
                await browser.close()
                
                if video_url:
                    result = PublishResult(
                        platform="tiktok",
                        video_id=self._extract_video_id(video_url),
                        url=video_url,
                        scheduled=False
                    )
                    logger.info(f"TikTok upload completed: {video_url}")
                    return result
                else:
                    logger.warning("TikTok upload completed but video URL not obtained")
                    return None

        except Exception as e:
            logger.error(f"Error uploading to TikTok: {e}")
            return None

    def _extract_video_id(self, url: str) -> str:
        """Extract video ID from TikTok URL"""
        try:
            # TikTok URLs typically look like: https://www.tiktok.com/@user/video/1234567890
            parts = url.split('/')
            if 'video' in parts:
                video_index = parts.index('video')
                if video_index + 1 < len(parts):
                    return parts[video_index + 1].split('?')[0]  # Remove query params
            
            # Fallback: use hash of URL
            return str(hash(url))
            
        except Exception as e:
            logger.error(f"Error extracting TikTok video ID: {e}")
            return str(hash(url))

    async def get_video_analytics(self, video_id: str) -> dict:
        """Get TikTok video analytics (limited without official API)"""
        logger.warning("TikTok analytics not available without official API access")
        return {
            "video_id": video_id,
            "views": 0,
            "likes": 0,
            "comments": 0,
            "shares": 0,
            "note": "Analytics not available - requires TikTok Business API"
        }

    async def validate_credentials(self, channel_name: str) -> bool:
        """Validate TikTok login status"""
        if not self.enabled:
            return False
            
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context()
                page = await context.new_page()
                
                await page.goto("https://www.tiktok.com/upload/")
                await page.wait_for_timeout(3000)
                
                # Check if redirected to login page
                is_logged_in = "login" not in page.url.lower()
                
                await browser.close()
                return is_logged_in
                
        except Exception as e:
            logger.error(f"Error validating TikTok credentials: {e}")
            return False

    def get_upload_requirements(self) -> dict:
        """Get TikTok upload requirements and guidelines"""
        return {
            "video_format": ["MP4", "MOV", "MPEG", "AVI", "WMV", "3GPP", "WEBM"],
            "max_duration_seconds": 60,
            "min_duration_seconds": 1,
            "max_file_size_mb": 500,
            "recommended_resolution": "1080x1920",
            "aspect_ratio": "9:16 (portrait)",
            "max_caption_length": 150,
            "max_hashtags": 10,
            "content_guidelines": [
                "Original content only",
                "No copyrighted music without permission", 
                "Follow community guidelines",
                "Vertical orientation preferred"
            ],
            "note": "TikTok publishing requires manual login and is experimental"
        }

    async def schedule_video(self, *args, **kwargs) -> Optional[PublishResult]:
        """TikTok doesn't support scheduling via web interface"""
        logger.warning("TikTok does not support video scheduling via web interface")
        return None