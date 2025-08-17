from typing import List, Dict
from datetime import datetime, timedelta
from models.schemas import TopicIdea
from collections import Counter
import json
import os
from loguru import logger

class TopicScorer:
    def __init__(self, content_root: str = "./data"):
        self.content_root = content_root
        self.weights_file = os.path.join(content_root, "topic_weights.json")
        self.history_file = os.path.join(content_root, "used_topics.json")
        self.load_weights()
        self.load_history()

    def load_weights(self):
        """Load scoring weights from file"""
        default_weights = {
            "recency_weight": 0.3,
            "cross_source_weight": 0.2,
            "novelty_weight": 0.25,
            "performance_weight": 0.25,
            "keyword_frequency_weight": 0.1
        }
        
        try:
            if os.path.exists(self.weights_file):
                with open(self.weights_file, 'r') as f:
                    self.weights = {**default_weights, **json.load(f)}
            else:
                self.weights = default_weights
        except Exception as e:
            logger.error(f"Error loading weights: {e}")
            self.weights = default_weights

    def save_weights(self):
        """Save updated weights to file"""
        try:
            os.makedirs(os.path.dirname(self.weights_file), exist_ok=True)
            with open(self.weights_file, 'w') as f:
                json.dump(self.weights, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving weights: {e}")

    def load_history(self):
        """Load history of used topics"""
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r') as f:
                    self.used_topics = json.load(f)
            else:
                self.used_topics = {}
        except Exception as e:
            logger.error(f"Error loading topic history: {e}")
            self.used_topics = {}

    def save_history(self):
        """Save updated topic history"""
        try:
            os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
            with open(self.history_file, 'w') as f:
                json.dump(self.used_topics, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving topic history: {e}")

    def score_and_rank(self, ideas: List[TopicIdea], channel: str) -> List[TopicIdea]:
        """Score and rank topic ideas for a specific channel"""
        if not ideas:
            return ideas

        # Calculate individual scores
        for idea in ideas:
            idea.score = self._calculate_composite_score(idea, ideas, channel)

        # Sort by score (highest first)
        ranked_ideas = sorted(ideas, key=lambda x: x.score, reverse=True)
        
        # Apply deduplication
        deduplicated = self._deduplicate_topics(ranked_ideas, channel)
        
        return deduplicated

    def _calculate_composite_score(self, idea: TopicIdea, all_ideas: List[TopicIdea], channel: str) -> float:
        """Calculate composite score for a topic idea"""
        scores = {
            'recency': self._score_recency(idea),
            'cross_source': self._score_cross_source_overlap(idea, all_ideas),
            'novelty': self._score_novelty(idea, channel),
            'performance': self._score_performance_potential(idea, channel),
            'keyword_frequency': self._score_keyword_frequency(idea, all_ideas)
        }
        
        # Weighted composite score
        composite_score = (
            scores['recency'] * self.weights['recency_weight'] +
            scores['cross_source'] * self.weights['cross_source_weight'] +
            scores['novelty'] * self.weights['novelty_weight'] +
            scores['performance'] * self.weights['performance_weight'] +
            scores['keyword_frequency'] * self.weights['keyword_frequency_weight']
        )
        
        return min(1.0, composite_score)

    def _score_recency(self, idea: TopicIdea) -> float:
        """Score based on how recent the topic is"""
        age_hours = (datetime.now() - idea.created_at).total_seconds() / 3600
        
        # Fresh content (0-24 hours) gets highest score
        if age_hours <= 24:
            return 1.0
        # Still good (24-72 hours)
        elif age_hours <= 72:
            return 0.8
        # Getting stale (72-120 hours)
        elif age_hours <= 120:
            return 0.5
        # Too old
        else:
            return 0.2

    def _score_cross_source_overlap(self, idea: TopicIdea, all_ideas: List[TopicIdea]) -> float:
        """Score based on how many sources mention similar topics"""
        similar_count = 0
        idea_keywords = set(idea.keywords)
        
        for other_idea in all_ideas:
            if other_idea.id != idea.id:
                other_keywords = set(other_idea.keywords)
                # Check for keyword overlap
                overlap = len(idea_keywords.intersection(other_keywords))
                if overlap >= 2:  # At least 2 keywords in common
                    similar_count += 1
        
        # More cross-source validation = higher score
        if similar_count >= 3:
            return 1.0
        elif similar_count >= 2:
            return 0.8
        elif similar_count >= 1:
            return 0.6
        else:
            return 0.3

    def _score_novelty(self, idea: TopicIdea, channel: str) -> float:
        """Score based on novelty (haven't covered similar topics recently)"""
        channel_history = self.used_topics.get(channel, [])
        
        # Check against topics used in last 14 days
        recent_cutoff = datetime.now() - timedelta(days=14)
        recent_topics = [
            topic for topic in channel_history 
            if datetime.fromisoformat(topic['used_at']) > recent_cutoff
        ]
        
        # Check for similar topics
        idea_keywords = set(idea.keywords)
        for recent_topic in recent_topics:
            recent_keywords = set(recent_topic['keywords'])
            overlap = len(idea_keywords.intersection(recent_keywords))
            
            # High overlap = low novelty
            if overlap >= 3:
                return 0.2
            elif overlap >= 2:
                return 0.5
        
        return 1.0  # Novel topic

    def _score_performance_potential(self, idea: TopicIdea, channel: str) -> float:
        """Score based on predicted performance using historical data"""
        channel_history = self.used_topics.get(channel, [])
        
        if not channel_history:
            return 0.5  # Neutral score for new channels
        
        # Analyze performance of similar topics
        idea_keywords = set(idea.keywords)
        similar_performances = []
        
        for topic in channel_history[-50]:  # Last 50 topics
            if 'performance' in topic:
                topic_keywords = set(topic['keywords'])
                overlap = len(idea_keywords.intersection(topic_keywords))
                
                if overlap >= 2:
                    # Normalize performance metrics
                    perf = topic['performance']
                    retention = perf.get('avg_view_duration_sec', 0) / perf.get('total_duration_sec', 1)
                    views_score = min(1.0, perf.get('views', 0) / 1000)  # Normalize to 1k views
                    
                    performance_score = (retention * 0.7 + views_score * 0.3)
                    similar_performances.append(performance_score)
        
        if similar_performances:
            return sum(similar_performances) / len(similar_performances)
        else:
            return 0.5  # Neutral for no similar topics

    def _score_keyword_frequency(self, idea: TopicIdea, all_ideas: List[TopicIdea]) -> float:
        """Score based on keyword frequency across all current ideas"""
        # Count keyword frequencies
        all_keywords = []
        for other_idea in all_ideas:
            all_keywords.extend(other_idea.keywords)
        
        keyword_counts = Counter(all_keywords)
        total_keywords = len(all_keywords)
        
        if total_keywords == 0:
            return 0.5
        
        # Calculate average frequency score for this idea's keywords
        freq_scores = []
        for keyword in idea.keywords:
            frequency = keyword_counts.get(keyword, 0) / total_keywords
            # Sweet spot: not too rare (0.01) not too common (0.1)
            if 0.02 <= frequency <= 0.08:
                freq_scores.append(1.0)
            elif 0.01 <= frequency <= 0.15:
                freq_scores.append(0.7)
            else:
                freq_scores.append(0.4)
        
        return sum(freq_scores) / len(freq_scores) if freq_scores else 0.5

    def _deduplicate_topics(self, ideas: List[TopicIdea], channel: str) -> List[TopicIdea]:
        """Remove duplicate or very similar topics"""
        deduplicated = []
        used_keyword_sets = []
        
        for idea in ideas:
            idea_keywords = set(idea.keywords)
            
            # Check for high similarity with already selected topics
            is_duplicate = False
            for used_keywords in used_keyword_sets:
                overlap = len(idea_keywords.intersection(used_keywords))
                overlap_ratio = overlap / max(len(idea_keywords), len(used_keywords))
                
                if overlap_ratio > 0.7:  # 70% keyword overlap = duplicate
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                deduplicated.append(idea)
                used_keyword_sets.append(idea_keywords)
        
        return deduplicated

    def mark_topic_used(self, topic_id: str, keywords: List[str], channel: str, performance_data: Dict = None):
        """Mark a topic as used and store performance data"""
        if channel not in self.used_topics:
            self.used_topics[channel] = []
        
        topic_record = {
            'topic_id': topic_id,
            'keywords': keywords,
            'used_at': datetime.now().isoformat(),
            'performance': performance_data
        }
        
        self.used_topics[channel].append(topic_record)
        
        # Keep only last 100 topics per channel
        self.used_topics[channel] = self.used_topics[channel][-100:]
        
        self.save_history()

    def update_weights_from_performance(self, performance_data: Dict):
        """Update scoring weights based on performance feedback"""
        # Simple learning: increase weights for factors that correlate with good performance
        if performance_data.get('avg_view_duration_sec', 0) > 15:  # Good retention
            self.weights['novelty_weight'] = min(0.4, self.weights['novelty_weight'] * 1.05)
        
        if performance_data.get('views', 0) > 5000:  # Good views
            self.weights['cross_source_weight'] = min(0.3, self.weights['cross_source_weight'] * 1.03)
        
        if performance_data.get('views', 0) < 500:  # Poor performance
            self.weights['recency_weight'] = max(0.1, self.weights['recency_weight'] * 0.98)
        
        self.save_weights()
        logger.info("Updated scoring weights based on performance")