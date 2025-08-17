import json
import os
from typing import Dict, List
from datetime import datetime, timedelta
from models.schemas import AnalyticsData
from research.score import TopicScorer
from analytics.fetch import AnalyticsFetcher
from loguru import logger

class LearningEngine:
    def __init__(self, content_root: str = "./data"):
        self.content_root = content_root
        self.learning_data_path = os.path.join(content_root, "learning_data.json")
        self.topic_scorer = TopicScorer(content_root)
        self.analytics_fetcher = AnalyticsFetcher()
        self.load_learning_data()

    def load_learning_data(self):
        """Load learning data from file"""
        try:
            if os.path.exists(self.learning_data_path):
                with open(self.learning_data_path, 'r') as f:
                    self.learning_data = json.load(f)
            else:
                self.learning_data = {
                    "keyword_performance": {},
                    "topic_patterns": {},
                    "successful_hooks": [],
                    "content_insights": {},
                    "last_updated": None
                }
        except Exception as e:
            logger.error(f"Error loading learning data: {e}")
            self.learning_data = {}

    def save_learning_data(self):
        """Save learning data to file"""
        try:
            self.learning_data["last_updated"] = datetime.now().isoformat()
            os.makedirs(os.path.dirname(self.learning_data_path), exist_ok=True)
            
            with open(self.learning_data_path, 'w') as f:
                json.dump(self.learning_data, f, indent=2)
                
            logger.info("Learning data saved")
        except Exception as e:
            logger.error(f"Error saving learning data: {e}")

    async def analyze_performance_and_learn(
        self, 
        video_id: str, 
        topic_keywords: List[str],
        hook: str,
        script: str,
        channel: str
    ):
        """Analyze video performance and update learning data"""
        try:
            # Get performance metrics
            metrics = await self.analytics_fetcher.calculate_performance_metrics(video_id)
            
            if not metrics:
                logger.warning(f"No metrics available for video {video_id}")
                return

            # Update keyword performance tracking
            self._update_keyword_performance(topic_keywords, metrics)
            
            # Analyze hook effectiveness
            self._analyze_hook_performance(hook, metrics)
            
            # Update content insights
            self._update_content_insights(script, metrics, channel)
            
            # Update topic scoring weights
            self._update_topic_weights(metrics)
            
            # Save updated learning data
            self.save_learning_data()
            
            logger.info(f"Learning update completed for video {video_id}")
            
        except Exception as e:
            logger.error(f"Error in learning analysis for {video_id}: {e}")

    def _update_keyword_performance(self, keywords: List[str], metrics: Dict):
        """Update keyword performance tracking"""
        performance_score = self._calculate_performance_score(metrics)
        
        for keyword in keywords:
            if keyword not in self.learning_data["keyword_performance"]:
                self.learning_data["keyword_performance"][keyword] = {
                    "total_videos": 0,
                    "total_performance": 0,
                    "avg_performance": 0,
                    "best_performance": 0,
                    "recent_trend": []
                }
            
            kp = self.learning_data["keyword_performance"][keyword]
            kp["total_videos"] += 1
            kp["total_performance"] += performance_score
            kp["avg_performance"] = kp["total_performance"] / kp["total_videos"]
            kp["best_performance"] = max(kp["best_performance"], performance_score)
            
            # Keep recent trend (last 10 videos)
            kp["recent_trend"].append(performance_score)
            kp["recent_trend"] = kp["recent_trend"][-10:]

    def _analyze_hook_performance(self, hook: str, metrics: Dict):
        """Analyze hook effectiveness"""
        performance_score = self._calculate_performance_score(metrics)
        
        # Extract hook patterns
        hook_length = len(hook.split())
        hook_has_question = "?" in hook
        hook_has_numbers = any(char.isdigit() for char in hook)
        hook_starts_with_action = hook.split()[0].lower() in ["discover", "learn", "watch", "see", "find", "get"]
        
        hook_data = {
            "text": hook,
            "performance": performance_score,
            "length_words": hook_length,
            "has_question": hook_has_question,
            "has_numbers": hook_has_numbers,
            "starts_with_action": hook_starts_with_action,
            "views": metrics.get("views", 0),
            "engagement_rate": metrics.get("engagement_rate", 0),
            "timestamp": datetime.now().isoformat()
        }
        
        # Keep top performing hooks
        self.learning_data["successful_hooks"].append(hook_data)
        
        # Sort by performance and keep top 50
        self.learning_data["successful_hooks"] = sorted(
            self.learning_data["successful_hooks"],
            key=lambda x: x["performance"],
            reverse=True
        )[:50]

    def _update_content_insights(self, script: str, metrics: Dict, channel: str):
        """Update content insights"""
        if channel not in self.learning_data["content_insights"]:
            self.learning_data["content_insights"][channel] = {
                "optimal_length": {"word_count": 0, "performance": 0},
                "successful_structures": [],
                "topic_preferences": {},
                "timing_insights": {}
            }
        
        insights = self.learning_data["content_insights"][channel]
        performance_score = self._calculate_performance_score(metrics)
        word_count = len(script.split())
        
        # Update optimal length tracking
        if performance_score > insights["optimal_length"]["performance"]:
            insights["optimal_length"] = {
                "word_count": word_count,
                "performance": performance_score
            }
        
        # Analyze script structure
        sentences = script.split('.')
        structure_pattern = {
            "sentence_count": len(sentences),
            "avg_sentence_length": sum(len(s.split()) for s in sentences) / len(sentences) if sentences else 0,
            "has_call_to_action": any(cta in script.lower() for cta in ["comment", "like", "subscribe", "share", "follow"]),
            "performance": performance_score
        }
        
        insights["successful_structures"].append(structure_pattern)
        insights["successful_structures"] = sorted(
            insights["successful_structures"],
            key=lambda x: x["performance"],
            reverse=True
        )[:20]

    def _update_topic_weights(self, metrics: Dict):
        """Update topic scoring weights based on performance"""
        performance_category = metrics.get("performance_category", "average")
        engagement_rate = metrics.get("engagement_rate", 0)
        retention_rate = metrics.get("retention_rate", 0)
        
        # Adjust weights based on performance
        current_weights = self.topic_scorer.weights
        
        if performance_category in ["viral", "high"]:
            # Successful video - slightly boost current strategy
            for weight_key in current_weights:
                current_weights[weight_key] *= 1.02  # Small boost
        
        elif performance_category == "low":
            # Poor performance - adjust weights
            if retention_rate < 30:
                # Low retention suggests content quality issues
                current_weights["novelty_weight"] *= 1.05
                current_weights["performance_weight"] *= 0.95
            
            if engagement_rate < 1.0:
                # Low engagement suggests topic relevance issues
                current_weights["cross_source_weight"] *= 1.03
                current_weights["recency_weight"] *= 0.98
        
        # Normalize weights to sum to 1.0
        total_weight = sum(current_weights.values())
        for key in current_weights:
            current_weights[key] /= total_weight
        
        self.topic_scorer.weights = current_weights
        self.topic_scorer.save_weights()

    def _calculate_performance_score(self, metrics: Dict) -> float:
        """Calculate normalized performance score (0-1)"""
        views = metrics.get("views", 0)
        engagement_rate = metrics.get("engagement_rate", 0)
        retention_rate = metrics.get("retention_rate", 0)
        
        # Normalize metrics (adjust these thresholds based on your channel performance)
        view_score = min(1.0, views / 10000)  # 10k views = max score
        engagement_score = min(1.0, engagement_rate / 5.0)  # 5% engagement = max score
        retention_score = retention_rate / 100.0  # Already in percentage
        
        # Weighted combination
        performance_score = (
            view_score * 0.5 +
            engagement_score * 0.3 +
            retention_score * 0.2
        )
        
        return performance_score

    def get_keyword_recommendations(self, niche: str, count: int = 10) -> List[str]:
        """Get recommended keywords based on historical performance"""
        try:
            # Filter keywords by niche relevance if possible
            keyword_performance = self.learning_data.get("keyword_performance", {})
            
            if not keyword_performance:
                return []
            
            # Sort by average performance
            sorted_keywords = sorted(
                keyword_performance.items(),
                key=lambda x: x[1]["avg_performance"],
                reverse=True
            )
            
            # Get top performing keywords
            recommendations = []
            for keyword, data in sorted_keywords[:count * 2]:  # Get extra to filter
                # Simple niche relevance check
                niche_words = niche.lower().split()
                if any(niche_word in keyword.lower() for niche_word in niche_words):
                    recommendations.append(keyword)
                elif len(recommendations) < count:  # Fill remaining slots with general good performers
                    recommendations.append(keyword)
                
                if len(recommendations) >= count:
                    break
            
            return recommendations[:count]
            
        except Exception as e:
            logger.error(f"Error getting keyword recommendations: {e}")
            return []

    def get_hook_recommendations(self, topic_keywords: List[str]) -> List[str]:
        """Get hook recommendations based on successful patterns"""
        try:
            successful_hooks = self.learning_data.get("successful_hooks", [])
            
            if not successful_hooks:
                return []
            
            # Filter hooks that might be relevant to current keywords
            relevant_hooks = []
            for hook_data in successful_hooks:
                hook_text = hook_data["text"].lower()
                
                # Check if hook contains any of the topic keywords
                if any(keyword.lower() in hook_text for keyword in topic_keywords):
                    relevant_hooks.append(hook_data)
            
            # If no relevant hooks found, use top performers
            if not relevant_hooks:
                relevant_hooks = successful_hooks[:10]
            
            # Extract hook patterns for generation
            hook_recommendations = []
            for hook_data in relevant_hooks[:5]:
                hook_recommendations.append(hook_data["text"])
            
            return hook_recommendations
            
        except Exception as e:
            logger.error(f"Error getting hook recommendations: {e}")
            return []

    def get_content_recommendations(self, channel: str) -> Dict:
        """Get content structure recommendations for a channel"""
        try:
            channel_insights = self.learning_data.get("content_insights", {}).get(channel, {})
            
            if not channel_insights:
                return {"message": "No historical data available for this channel"}
            
            recommendations = {}
            
            # Optimal word count
            optimal_length = channel_insights.get("optimal_length", {})
            if optimal_length.get("word_count"):
                recommendations["optimal_word_count"] = optimal_length["word_count"]
            
            # Best performing structure
            successful_structures = channel_insights.get("successful_structures", [])
            if successful_structures:
                best_structure = successful_structures[0]
                recommendations["recommended_structure"] = {
                    "sentence_count": best_structure["sentence_count"],
                    "avg_sentence_length": round(best_structure["avg_sentence_length"], 1),
                    "include_call_to_action": best_structure["has_call_to_action"]
                }
            
            return recommendations
            
        except Exception as e:
            logger.error(f"Error getting content recommendations: {e}")
            return {"error": "Failed to generate recommendations"}

    async def generate_performance_report(self, days_back: int = 30) -> Dict:
        """Generate comprehensive performance report"""
        try:
            report = {
                "report_period": f"Last {days_back} days",
                "generated_at": datetime.now().isoformat(),
                "keyword_insights": {},
                "hook_insights": {},
                "content_insights": {},
                "trends": {}
            }
            
            # Keyword performance insights
            keyword_performance = self.learning_data.get("keyword_performance", {})
            if keyword_performance:
                top_keywords = sorted(
                    keyword_performance.items(),
                    key=lambda x: x[1]["avg_performance"],
                    reverse=True
                )[:10]
                
                report["keyword_insights"] = {
                    "top_performing": [
                        {"keyword": k, "avg_performance": round(v["avg_performance"], 3)}
                        for k, v in top_keywords
                    ]
                }
            
            # Hook performance insights
            successful_hooks = self.learning_data.get("successful_hooks", [])
            if successful_hooks:
                # Analyze hook patterns
                avg_length = sum(h["length_words"] for h in successful_hooks) / len(successful_hooks)
                question_success_rate = len([h for h in successful_hooks if h["has_question"]]) / len(successful_hooks)
                number_success_rate = len([h for h in successful_hooks if h["has_numbers"]]) / len(successful_hooks)
                
                report["hook_insights"] = {
                    "optimal_length_words": round(avg_length, 1),
                    "question_hooks_success_rate": round(question_success_rate * 100, 1),
                    "hooks_with_numbers_success_rate": round(number_success_rate * 100, 1),
                    "top_hooks": [h["text"] for h in successful_hooks[:5]]
                }
            
            # Content insights by channel
            content_insights = self.learning_data.get("content_insights", {})
            report["content_insights"] = content_insights
            
            return report
            
        except Exception as e:
            logger.error(f"Error generating performance report: {e}")
            return {"error": "Failed to generate report"}

    def reset_learning_data(self):
        """Reset all learning data (use with caution)"""
        self.learning_data = {
            "keyword_performance": {},
            "topic_patterns": {},
            "successful_hooks": [],
            "content_insights": {},
            "last_updated": None
        }
        self.save_learning_data()
        logger.info("Learning data has been reset")