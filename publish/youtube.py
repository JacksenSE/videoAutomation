import os
import json
import asyncio
from typing import Optional, Dict
from datetime import datetime, timezone
import pickle
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from models.schemas import PublishResult, AnalyticsData
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

class YouTubePublisher:
    def __init__(self):
        self.client_id = os.getenv("YOUTUBE_CLIENT_ID")
        self.client_secret = os.getenv("YOUTUBE_CLIENT_SECRET")
        self.redirect_uri = os.getenv("YOUTUBE_REDIRECT_URI", "http://localhost:5317/oauth2callback")
        self.scopes = [
            'https://www.googleapis.com/auth/youtube.upload',
            'https://www.googleapis.com/auth/youtube.readonly'
        ]

    async def upload_video(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list,
        channel_token_path: str,
        thumbnail_path: Optional[str] = None,
        scheduled_time: Optional[datetime] = None
    ) -> Optional[PublishResult]:
        """Upload video to YouTube"""
        try:
            # Get authenticated service
            service = await self._get_authenticated_service(channel_token_path)
            if not service:
                logger.error("Failed to authenticate with YouTube")
                return None

            # Prepare video metadata
            body = {
                'snippet': {
                    'title': title,
                    'description': description,
                    'tags': tags,
                    'categoryId': '22',  # People & Blogs
                    'defaultLanguage': 'en',
                    'defaultAudioLanguage': 'en'
                },
                'status': {
                    'privacyStatus': 'public' if not scheduled_time else 'private',
                    'selfDeclaredMadeForKids': False,
                    'publishAt': scheduled_time.isoformat() if scheduled_time else None
                }
            }

            # Create media upload
            media = MediaFileUpload(
                video_path,
                chunksize=-1,
                resumable=True,
                mimetype='video/mp4'
            )

            # Upload video
            request = service.videos().insert(
                part=','.join(body.keys()),
                body=body,
                media_body=media
            )

            video_id = None
            response = None
            error = None
            retry_count = 0
            max_retries = 3

            while response is None and retry_count < max_retries:
                try:
                    status, response = request.next_chunk()
                    if response is not None:
                        if 'id' in response:
                            video_id = response['id']
                            logger.info(f"Video uploaded successfully: {video_id}")
                            break
                        else:
                            error = f"Upload failed: {response}"
                            logger.error(error)
                            return None
                except Exception as e:
                    if "quotaExceeded" in str(e):
                        logger.error("YouTube API quota exceeded")
                        return None
                    
                    retry_count += 1
                    logger.warning(f"Upload error (retry {retry_count}): {e}")
                    if retry_count < max_retries:
                        await asyncio.sleep(2 ** retry_count)  # Exponential backoff
                    else:
                        logger.error(f"Max retries exceeded: {e}")
                        return None

            if not video_id:
                return None

            # Upload thumbnail if provided
            if thumbnail_path and os.path.exists(thumbnail_path):
                await self._upload_thumbnail(service, video_id, thumbnail_path)

            # Create result
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            result = PublishResult(
                platform="youtube",
                video_id=video_id,
                url=video_url,
                scheduled=scheduled_time is not None
            )

            logger.info(f"Successfully published to YouTube: {video_url}")
            return result

        except Exception as e:
            logger.error(f"Error uploading to YouTube: {e}")
            return None

    async def _get_authenticated_service(self, token_path: str):
        """Get authenticated YouTube service"""
        try:
            creds = None
            
            # Load existing token
            if os.path.exists(token_path):
                with open(token_path, 'rb') as token:
                    creds = pickle.load(token)

            # If no valid credentials, run OAuth flow
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    try:
                        creds.refresh(Request())
                    except Exception as e:
                        logger.warning(f"Token refresh failed: {e}")
                        creds = None

                if not creds:
                    logger.info(f"Starting OAuth flow for {token_path}")
                    flow = Flow.from_client_config({
                        "web": {
                            "client_id": self.client_id,
                            "client_secret": self.client_secret,
                            "redirect_uris": [self.redirect_uri],
                            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                            "token_uri": "https://oauth2.googleapis.com/token"
                        }
                    }, self.scopes)
                    
                    flow.redirect_uri = self.redirect_uri
                    
                    # This would need to be handled by the web interface
                    # For now, we'll return None to indicate auth needed
                    logger.error("OAuth authentication required - use web interface")
                    return None

                # Save credentials
                os.makedirs(os.path.dirname(token_path), exist_ok=True)
                with open(token_path, 'wb') as token:
                    pickle.dump(creds, token)

            # Build service
            service = build('youtube', 'v3', credentials=creds)
            return service

        except Exception as e:
            logger.error(f"Error getting YouTube service: {e}")
            return None

    async def _upload_thumbnail(self, service, video_id: str, thumbnail_path: str):
        """Upload thumbnail for video"""
        try:
            media = MediaFileUpload(thumbnail_path, mimetype='image/jpeg')
            service.thumbnails().set(
                videoId=video_id,
                media_body=media
            ).execute()
            
            logger.info(f"Thumbnail uploaded for video {video_id}")
            
        except Exception as e:
            logger.warning(f"Error uploading thumbnail: {e}")

    async def get_video_analytics(
        self, 
        video_id: str, 
        channel_token_path: str
    ) -> Optional[AnalyticsData]:
        """Get analytics data for a video"""
        try:
            service = await self._get_authenticated_service(channel_token_path)
            if not service:
                return None

            # Get video statistics
            request = service.videos().list(
                part='statistics',
                id=video_id
            )
            response = request.execute()

            if not response.get('items'):
                logger.warning(f"No analytics found for video {video_id}")
                return None

            stats = response['items'][0]['statistics']
            
            # Convert to AnalyticsData
            analytics = AnalyticsData(
                video_id=video_id,
                views=int(stats.get('viewCount', 0)),
                likes=int(stats.get('likeCount', 0)),
                avg_view_duration_sec=0.0,  # Not available in basic stats
                click_through_rate=None,
                audience_retention=None
            )

            # Try to get more detailed analytics from YouTube Analytics API
            try:
                analytics_service = build('youtubeAnalytics', 'v2', credentials=service._http.credentials)
                
                # Get average view duration
                analytics_request = analytics_service.reports().query(
                    ids=f'channel==MINE',
                    startDate='2024-01-01',
                    endDate=datetime.now().strftime('%Y-%m-%d'),
                    metrics='averageViewDuration,averageViewPercentage',
                    filters=f'video=={video_id}'
                )
                
                analytics_response = analytics_request.execute()
                
                if analytics_response.get('rows'):
                    row = analytics_response['rows'][0]
                    analytics.avg_view_duration_sec = float(row[0])
                    # avg_view_percentage = float(row[1])
                
            except Exception as e:
                logger.warning(f"Could not get detailed analytics: {e}")

            return analytics

        except Exception as e:
            logger.error(f"Error getting video analytics: {e}")
            return None

    async def get_channel_info(self, channel_token_path: str) -> Optional[Dict]:
        """Get channel information"""
        try:
            service = await self._get_authenticated_service(channel_token_path)
            if not service:
                return None

            request = service.channels().list(
                part='snippet,statistics',
                mine=True
            )
            response = request.execute()

            if response.get('items'):
                return response['items'][0]
            
            return None

        except Exception as e:
            logger.error(f"Error getting channel info: {e}")
            return None

    def get_oauth_url(self, channel_name: str, state: Optional[str] = None) -> str:
        """Generate OAuth URL for channel authentication"""
        try:
            flow = Flow.from_client_config({
                "web": {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uris": [self.redirect_uri],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token"
                }
            }, self.scopes)
            
            flow.redirect_uri = self.redirect_uri
            
            auth_url, _ = flow.authorization_url(
                access_type='offline',
                include_granted_scopes='true',
                state=state or channel_name
            )
            
            return auth_url

        except Exception as e:
            logger.error(f"Error generating OAuth URL: {e}")
            return ""

    async def handle_oauth_callback(self, code: str, state: str) -> bool:
        """Handle OAuth callback and save credentials"""
        try:
            flow = Flow.from_client_config({
                "web": {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uris": [self.redirect_uri],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token"
                }
            }, self.scopes)
            
            flow.redirect_uri = self.redirect_uri
            flow.fetch_token(code=code)
            
            # Save credentials
            channel_name = state  # We passed channel name as state
            token_path = f"./tokens/{channel_name.lower()}.json"
            os.makedirs(os.path.dirname(token_path), exist_ok=True)
            
            with open(token_path, 'wb') as token:
                pickle.dump(flow.credentials, token)
            
            logger.info(f"OAuth credentials saved for channel: {channel_name}")
            return True

        except Exception as e:
            logger.error(f"Error handling OAuth callback: {e}")
            return False

    async def validate_video_for_shorts(self, video_path: str) -> Dict:
        """Validate video meets YouTube Shorts requirements"""
        try:
            import subprocess
            import json
            
            # Get video info
            cmd = [
                'ffprobe', '-v', 'quiet',
                '-print_format', 'json',
                '-show_format', '-show_streams',
                video_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                return {"valid": False, "errors": ["Could not analyze video file"]}
            
            data = json.loads(result.stdout)
            video_stream = next((s for s in data['streams'] if s['codec_type'] == 'video'), None)
            
            if not video_stream:
                return {"valid": False, "errors": ["No video stream found"]}
            
            errors = []
            warnings = []
            
            # Check duration (must be ≤60 seconds)
            duration = float(data['format']['duration'])
            if duration > 60:
                errors.append(f"Duration {duration:.1f}s exceeds 60s limit for Shorts")
            
            # Check aspect ratio (should be 9:16 or close)
            width = int(video_stream['width'])
            height = int(video_stream['height'])
            aspect_ratio = width / height
            
            if not (0.5 <= aspect_ratio <= 0.6):  # 9:16 = 0.5625
                warnings.append(f"Aspect ratio {aspect_ratio:.2f} may not be optimal for Shorts (recommend 9:16)")
            
            # Check resolution
            if height < 1920:
                warnings.append(f"Resolution {width}x{height} is lower than recommended 1080x1920")
            
            return {
                "valid": len(errors) == 0,
                "errors": errors,
                "warnings": warnings,
                "duration": duration,
                "resolution": f"{width}x{height}",
                "aspect_ratio": aspect_ratio
            }

        except Exception as e:
            logger.error(f"Error validating video for Shorts: {e}")
            return {"valid": False, "errors": ["Validation failed"]}