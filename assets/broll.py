import os
import asyncio
import aiohttp
import json
import random
import re
from typing import List, Optional
from urllib.parse import urlencode
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

class BRollProvider:
    def __init__(self, pexels_api_key: Optional[str] = None):
        self.pexels_api_key = pexels_api_key or os.getenv("PEXELS_API_KEY")
        self.local_assets_dir = "./data/assets/stock"
        
        # Ensure local assets directory exists
        os.makedirs(self.local_assets_dir, exist_ok=True)

    async def fetch_broll_clips(
        self, 
        keywords: List[str], 
        niche: str, 
        count: int = 5,
        duration_range: tuple = (5, 10)
    ) -> List[str]:
        """Fetch B-roll video clips based on keywords and niche"""
        clips = []
        
        # Try Pexels API first (if key available)
        if self.pexels_api_key:
            pexels_clips = await self._fetch_from_pexels(keywords, niche, count)
            clips.extend(pexels_clips)
        
        # Fall back to local stock footage if needed
        if len(clips) < count:
            local_clips = self._get_local_stock_clips(keywords, niche, count - len(clips))
            clips.extend(local_clips)
        
        # Try to get stock images as well for middle section
        if self.pexels_api_key:
            stock_images = await self._fetch_stock_images(keywords, niche, 2)
            clips.extend(stock_images)
        
        # Generate abstract backgrounds if still not enough
        if len(clips) < count:
            abstract_clips = await self._generate_abstract_backgrounds(count - len(clips))
            clips.extend(abstract_clips)
        
        return clips[:count]

    async def _fetch_from_pexels(self, keywords: List[str], niche: str, count: int) -> List[str]:
        """Fetch video clips from Pexels API"""
        clips = []
        
        try:
            # Create search query
            search_terms = self._get_search_terms_for_niche(niche) + keywords
            query = " ".join(search_terms[:3])  # Use top 3 terms
            
            headers = {
                'Authorization': self.pexels_api_key,
                'User-Agent': 'AutoShorts/1.0'
            }
            
            params = {
                'query': query,
                'orientation': 'portrait',  # Vertical videos for shorts
                'size': 'medium',
                'per_page': min(count * 2, 20)  # Get more options to filter
            }
            
            url = f"https://api.pexels.com/videos/search?{urlencode(params)}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        videos = data.get('videos', [])
                        
                        for video in videos:
                            if len(clips) >= count:
                                break
                            
                            # Find suitable video file (prefer smaller sizes for efficiency)
                            video_files = video.get('video_files', [])
                            suitable_file = self._find_suitable_video_file(video_files)
                            
                            if suitable_file:
                                # Download and save locally
                                local_path = await self._download_video(
                                    suitable_file['link'], 
                                    f"pexels_{video['id']}.mp4"
                                )
                                if local_path:
                                    clips.append(local_path)
                    
                    else:
                        logger.warning(f"Pexels API returned status {response.status}")
        
        except Exception as e:
            logger.error(f"Error fetching from Pexels: {e}")
        
        return clips

    async def _fetch_stock_images(self, keywords: List[str], niche: str, count: int) -> List[str]:
        """Fetch stock images from Pexels API for middle section visuals"""
        images = []
        
        try:
            # Create search query
            search_terms = self._get_search_terms_for_niche(niche) + keywords
            query = " ".join(search_terms[:3])
            
            headers = {
                'Authorization': self.pexels_api_key,
                'User-Agent': 'AutoShorts/1.0'
            }
            
            params = {
                'query': query,
                'orientation': 'landscape',  # Good for middle section
                'size': 'large',
                'per_page': min(count * 2, 15)
            }
            
            url = f"https://api.pexels.com/v1/search?{urlencode(params)}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        photos = data.get('photos', [])
                        
                        for photo in photos:
                            if len(images) >= count:
                                break
                            
                            # Get medium size image
                            image_url = photo['src']['large']
                            
                            # Download and save locally
                            local_path = await self._download_image(
                                image_url, 
                                f"pexels_img_{photo['id']}.jpg"
                            )
                            if local_path:
                                images.append(local_path)
                    
                    else:
                        logger.warning(f"Pexels Images API returned status {response.status}")
        
        except Exception as e:
            logger.error(f"Error fetching stock images from Pexels: {e}")
        
        return images

    async def _download_image(self, url: str, filename: str) -> Optional[str]:
        """Download image file to local storage"""
        try:
            output_path = os.path.join(self.local_assets_dir, filename)
            
            # Skip if already downloaded
            if os.path.exists(output_path):
                return output_path
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        with open(output_path, 'wb') as f:
                            async for chunk in response.content.iter_chunked(8192):
                                f.write(chunk)
                        
                        logger.info(f"Downloaded stock image: {filename}")
                        return output_path
        
        except Exception as e:
            logger.error(f"Error downloading image {url}: {e}")
        
        return None

    def _find_suitable_video_file(self, video_files: List[dict]) -> Optional[dict]:
        """Find the most suitable video file from Pexels response"""
        # Prefer HD quality with reasonable file size
        preferred_qualities = ['hd', 'sd']
        
        for quality in preferred_qualities:
            for file in video_files:
                if (file.get('quality') == quality and 
                    file.get('file_type') == 'video/mp4'):
                    return file
        
        # Fallback to any mp4 file
        for file in video_files:
            if file.get('file_type') == 'video/mp4':
                return file
        
        return None

    async def _download_video(self, url: str, filename: str) -> Optional[str]:
        """Download video file to local storage"""
        try:
            output_path = os.path.join(self.local_assets_dir, filename)
            
            # Skip if already downloaded
            if os.path.exists(output_path):
                return output_path
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        with open(output_path, 'wb') as f:
                            async for chunk in response.content.iter_chunked(8192):
                                f.write(chunk)
                        
                        logger.info(f"Downloaded B-roll clip: {filename}")
                        return output_path
        
        except Exception as e:
            logger.error(f"Error downloading video {url}: {e}")
        
        return None

    def _get_local_stock_clips(self, keywords: List[str], niche: str, count: int) -> List[str]:
        """Get clips from local stock footage directory"""
        clips = []
        
        # Look for existing local clips
        if os.path.exists(self.local_assets_dir):
            local_files = [
                f for f in os.listdir(self.local_assets_dir) 
                if f.endswith(('.mp4', '.mov', '.avi'))
            ]
            
            # Randomly select from available clips
            selected_files = random.sample(local_files, min(count, len(local_files)))
            clips = [os.path.join(self.local_assets_dir, f) for f in selected_files]
        
        return clips

    async def _generate_abstract_backgrounds(self, count: int) -> List[str]:
        """Generate simple abstract background videos using FFmpeg"""
        clips = []
        
        try:
            import subprocess
            
            for i in range(count):
                filename = f"abstract_bg_{i}_{random.randint(1000, 9999)}.mp4"
                output_path = os.path.join(self.local_assets_dir, filename)
                
                # Generate simple gradient background with subtle animation
                colors = [
                    "gradient=radial:c0=0x1a1a1a:c1=0x333333",
                    "gradient=radial:c0=0x2a2a2a:c1=0x1a1a1a",
                    "gradient=linear:90:c0=0x1a1a2e:c1=0x16213e",
                    "gradient=linear:45:c0=0x2d1b69:c1=0x11998e"
                ]
                
                color = random.choice(colors)
                
                # Create 8-second abstract background
                cmd = [
                    'ffmpeg', '-y',
                    '-f', 'lavfi',
                    '-i', f'color=c=black:s=1080x1920:d=8',
                    '-vf', f'{color},scale=1080:1920',
                    '-t', '8',
                    '-pix_fmt', 'yuv420p',
                    output_path
                ]
                
                result = subprocess.run(cmd, capture_output=True, text=True)
                
                if result.returncode == 0:
                    clips.append(output_path)
                    logger.info(f"Generated abstract background: {filename}")
                else:
                    logger.error(f"Error generating abstract background: {result.stderr}")
        
        except Exception as e:
            logger.error(f"Error generating abstract backgrounds: {e}")
        
        return clips

    def _get_search_terms_for_niche(self, niche: str) -> List[str]:
        """Get relevant search terms for B-roll based on niche"""
        niche_terms = {
            'tech': ['technology', 'computer', 'coding', 'digital', 'innovation'],
            'ai': ['artificial intelligence', 'robot', 'futuristic', 'data', 'automation'],
            'finance': ['money', 'business', 'investment', 'growth', 'success'],
            'meditation': ['nature', 'peaceful', 'zen', 'calm', 'mindfulness'],
            'culture': ['lifestyle', 'people', 'city', 'art', 'creative'],
            'entertainment': ['lifestyle', 'fun', 'party', 'music', 'celebration']
        }
        
        niche_lower = niche.lower()
        for key, terms in niche_terms.items():
            if key in niche_lower:
                return terms
        
        return ['abstract', 'background', 'minimal']  # Default fallback

    def get_topic_keywords_from_script(self, script_text: str) -> List[str]:
        """Extract visual keywords from script for better B-roll matching"""
        # Extract nouns and important terms that would make good visuals
        visual_keywords = []
        
        # Common visual terms that work well for stock footage
        visual_terms = [
            'technology', 'computer', 'phone', 'app', 'software', 'ai', 'robot',
            'business', 'office', 'meeting', 'team', 'work', 'success',
            'money', 'finance', 'investment', 'growth', 'chart', 'data',
            'nature', 'city', 'people', 'lifestyle', 'health', 'fitness',
            'education', 'learning', 'book', 'study', 'innovation', 'future'
        ]
        
        script_lower = script_text.lower()
        for term in visual_terms:
            if term in script_lower:
                visual_keywords.append(term)
        
        # Also extract capitalized words (likely proper nouns/important terms)
        words = re.findall(r'\b[A-Z][a-z]+\b', script_text)
        visual_keywords.extend(words[:3])  # Add up to 3 capitalized terms
        
        return visual_keywords[:5]  # Return top 5 keywords

    async def organize_clips_by_duration(self, clips: List[str]) -> dict:
        """Organize clips by their duration for better sequencing"""
        organized = {'short': [], 'medium': [], 'long': []}
        
        for clip in clips:
            try:
                # Get video duration using ffprobe
                import subprocess
                import json
                
                cmd = [
                    'ffprobe', '-v', 'quiet',
                    '-print_format', 'json',
                    '-show_format',
                    clip
                ]
                
                result = subprocess.run(cmd, capture_output=True, text=True)
                
                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    duration = float(data['format']['duration'])
                    
                    if duration <= 5:
                        organized['short'].append(clip)
                    elif duration <= 10:
                        organized['medium'].append(clip)
                    else:
                        organized['long'].append(clip)
                else:
                    # Default to medium if duration detection fails
                    organized['medium'].append(clip)
            
            except Exception as e:
                logger.error(f"Error getting duration for {clip}: {e}")
                organized['medium'].append(clip)
        
        return organized

    def cleanup_old_clips(self, days: int = 7):
        """Clean up old downloaded clips to save space"""
        try:
            import time
            
            if not os.path.exists(self.local_assets_dir):
                return
            
            cutoff_time = time.time() - (days * 24 * 60 * 60)
            
            for filename in os.listdir(self.local_assets_dir):
                filepath = os.path.join(self.local_assets_dir, filename)
                
                if os.path.isfile(filepath):
                    file_time = os.path.getmtime(filepath)
                    
                    if file_time < cutoff_time:
                        os.remove(filepath)
                        logger.info(f"Cleaned up old clip: {filename}")
        
        except Exception as e:
            logger.error(f"Error cleaning up clips: {e}")