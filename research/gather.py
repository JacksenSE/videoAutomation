import asyncio
import aiohttp
import feedparser
import json
import re
from typing import List, Dict
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from models.schemas import TopicIdea, TopicSource
from loguru import logger

class TopicGatherer:
    def __init__(self):
        self.session: aiohttp.ClientSession = None
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def gather_for_channel(self, channel_niche: str, count: int = 50) -> List[TopicIdea]:
        """Gather trending topics for a specific channel niche"""
        ideas = []
        
        # YouTube trending
        yt_ideas = await self._gather_youtube_trending(channel_niche, count // 3)
        ideas.extend(yt_ideas)
        
        # RSS feeds
        rss_ideas = await self._gather_rss_feeds(channel_niche, count // 3)
        ideas.extend(rss_ideas)
        
        # Reddit (optional)
        reddit_ideas = await self._gather_reddit_topics(channel_niche, count // 3)
        ideas.extend(reddit_ideas)
        
        # Sort by relevance and return top candidates
        return sorted(ideas, key=lambda x: x.score, reverse=True)[:count]

    async def _gather_youtube_trending(self, niche: str, count: int) -> List[TopicIdea]:
        """Scrape YouTube trending page for relevant topics"""
        ideas = []
        try:
            url = "https://www.youtube.com/feed/trending"
            async with self.session.get(url) as response:
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                # Extract video titles and descriptions
                video_elements = soup.find_all('a', {'id': 'video-title'})[:50]
                
                for element in video_elements:
                    title = element.get('title', '').strip()
                    if title and self._is_relevant_to_niche(title, niche):
                        idea_id = f"yt_{hash(title)}_{int(datetime.now().timestamp())}"
                        
                        ideas.append(TopicIdea(
                            id=idea_id,
                            seed_source=TopicSource.YT_TRENDING,
                            title=title,
                            angle=self._extract_angle(title),
                            keywords=self._extract_keywords(title),
                            score=self._calculate_relevance_score(title, niche)
                        ))
                        
                        if len(ideas) >= count:
                            break
                            
        except Exception as e:
            logger.error(f"Error gathering YouTube trending: {e}")
            
        return ideas

    async def _gather_rss_feeds(self, niche: str, count: int) -> List[TopicIdea]:
        """Gather from RSS feeds relevant to the niche"""
        ideas = []
        feeds = self._get_rss_feeds_for_niche(niche)
        
        for feed_url in feeds[:3]:  # Limit to 3 feeds per niche
            try:
                async with self.session.get(feed_url) as response:
                    content = await response.text()
                    feed = feedparser.parse(content)
                    
                    for entry in feed.entries[:10]:  # Top 10 from each feed
                        title = entry.title
                        if self._is_recent(entry.get('published_parsed')) and \
                           self._is_relevant_to_niche(title, niche):
                            
                            idea_id = f"rss_{hash(title)}_{int(datetime.now().timestamp())}"
                            
                            ideas.append(TopicIdea(
                                id=idea_id,
                                seed_source=TopicSource.RSS,
                                title=title,
                                angle=self._extract_angle(title),
                                keywords=self._extract_keywords(title),
                                score=self._calculate_relevance_score(title, niche)
                            ))
                            
                            if len(ideas) >= count:
                                break
                                
                if len(ideas) >= count:
                    break
                    
            except Exception as e:
                logger.error(f"Error gathering RSS feed {feed_url}: {e}")
                
        return ideas

    async def _gather_reddit_topics(self, niche: str, count: int) -> List[TopicIdea]:
        """Gather from relevant subreddit JSON feeds"""
        ideas = []
        subreddits = self._get_subreddits_for_niche(niche)
        
        for subreddit in subreddits[:2]:  # Limit to 2 subreddits
            try:
                url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit=25"
                headers = {'User-Agent': 'AutoShorts/1.0'}
                
                async with self.session.get(url, headers=headers) as response:
                    data = await response.json()
                    
                    for post in data['data']['children']:
                        post_data = post['data']
                        title = post_data['title']
                        
                        if self._is_relevant_to_niche(title, niche) and \
                           post_data['score'] > 100:  # Popular posts only
                            
                            idea_id = f"reddit_{hash(title)}_{int(datetime.now().timestamp())}"
                            
                            ideas.append(TopicIdea(
                                id=idea_id,
                                seed_source=TopicSource.REDDIT,
                                title=title,
                                angle=self._extract_angle(title),
                                keywords=self._extract_keywords(title),
                                score=self._calculate_relevance_score(title, niche) * 0.8  # Slight penalty for Reddit
                            ))
                            
                            if len(ideas) >= count:
                                break
                                
                if len(ideas) >= count:
                    break
                    
            except Exception as e:
                logger.error(f"Error gathering Reddit r/{subreddit}: {e}")
                
        return ideas

    def _is_relevant_to_niche(self, title: str, niche: str) -> bool:
        """Check if title is relevant to the channel niche"""
        title_lower = title.lower()
        niche_keywords = niche.lower().split(', ')
        
        # Check for keyword matches
        for keyword in niche_keywords:
            if keyword in title_lower:
                return True
                
        return False

    def _calculate_relevance_score(self, title: str, niche: str) -> float:
        """Calculate relevance score (0-1) based on keyword matching"""
        title_lower = title.lower()
        niche_keywords = niche.lower().split(', ')
        
        matches = sum(1 for keyword in niche_keywords if keyword in title_lower)
        max_score = len(niche_keywords)
        
        base_score = matches / max_score if max_score > 0 else 0
        
        # Boost for trending indicators
        trending_indicators = ['viral', 'breaking', 'new', 'trending', 'latest', '2024']
        trend_boost = sum(0.1 for indicator in trending_indicators if indicator in title_lower)
        
        return min(1.0, base_score + trend_boost)

    def _extract_angle(self, title: str) -> str:
        """Extract the main angle/hook from the title"""
        # Remove common prefixes and extract core message
        cleaned = re.sub(r'^(BREAKING:|NEW:|VIRAL:|TRENDING:)\s*', '', title, flags=re.IGNORECASE)
        return cleaned[:100]  # Limit length

    def _extract_keywords(self, title: str) -> List[str]:
        """Extract relevant keywords from title"""
        # Simple keyword extraction
        words = re.findall(r'\w+', title.lower())
        # Filter out common stop words
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'is', 'was', 'are', 'were', 'be', 'been', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should'}
        keywords = [word for word in words if len(word) > 3 and word not in stop_words]
        return keywords[:5]  # Top 5 keywords

    def _is_recent(self, published_parsed) -> bool:
        """Check if content is recent (within last 5 days)"""
        if not published_parsed:
            return True  # Assume recent if no date
            
        pub_date = datetime(*published_parsed[:6])
        return (datetime.now() - pub_date) <= timedelta(days=5)

    def _get_rss_feeds_for_niche(self, niche: str) -> List[str]:
        """Get RSS feeds relevant to the niche"""
        feed_mapping = {
            'tech': ['https://techcrunch.com/feed/', 'https://feeds.feedburner.com/oreilly/radar'],
            'ai': ['https://www.artificialintelligence-news.com/feed/', 'https://feeds.feedburner.com/oreilly/radar'],
            'finance': ['https://feeds.feedburner.com/zerohedge/feed', 'https://www.marketwatch.com/rss/topstories'],
            'meditation': ['https://www.mindful.org/feed/', 'https://tinybuddha.com/feed/'],
            'culture': ['https://www.vulture.com/rss/', 'https://pitchfork.com/rss/news/'],
            'entertainment': ['https://www.eonline.com/news/rss', 'https://www.tmz.com/rss.xml']
        }
        
        feeds = []
        niche_lower = niche.lower()
        
        for category, category_feeds in feed_mapping.items():
            if category in niche_lower:
                feeds.extend(category_feeds)
                
        return feeds[:3]  # Max 3 feeds

    def _get_subreddits_for_niche(self, niche: str) -> List[str]:
        """Get relevant subreddits for the niche"""
        subreddit_mapping = {
            'tech': ['technology', 'programming'],
            'ai': ['MachineLearning', 'artificial'],
            'finance': ['personalfinance', 'investing'],
            'meditation': ['Meditation', 'mindfulness'],
            'culture': ['popculture', 'entertainment'],
            'entertainment': ['movies', 'television']
        }
        
        subreddits = []
        niche_lower = niche.lower()
        
        for category, category_subs in subreddit_mapping.items():
            if category in niche_lower:
                subreddits.extend(category_subs)
                
        return subreddits[:2]  # Max 2 subreddits