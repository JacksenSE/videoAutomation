import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from models.schemas import TopicIdea, TopicSource
from orchestrator.pipeline import VideoGenerationPipeline
from research.score import TopicScorer
from nlp.safety import SafetyChecker

@pytest.fixture
def sample_topic_idea():
    return TopicIdea(
        id="test_123",
        seed_source=TopicSource.YT_TRENDING,
        title="Amazing AI Tool Changes Everything",
        angle="Revolutionary AI breakthrough",
        keywords=["ai", "technology", "breakthrough"],
        score=0.85
    )

@pytest.fixture
def mock_channel_config():
    return {
        "name": "TestChannel",
        "niche": "technology, AI tools",
        "banned_terms": ["politics", "medical"],
        "local_time": "09:00",
        "style": "clean-bold",
        "youtube_oauth_token": "tokens/test.json"
    }

class TestTopicScorer:
    def test_calculate_relevance_score(self):
        scorer = TopicScorer()
        
        # High relevance
        score = scorer._calculate_relevance_score(
            "Amazing AI breakthrough in technology", 
            "technology, AI tools"
        )
        assert score > 0.5
        
        # Low relevance
        score = scorer._calculate_relevance_score(
            "Cooking recipe for pasta", 
            "technology, AI tools"
        )
        assert score < 0.3

    def test_extract_keywords(self):
        scorer = TopicScorer()
        keywords = scorer._extract_keywords("Amazing AI breakthrough technology")
        
        assert "amazing" in keywords
        assert "breakthrough" in keywords
        assert "technology" in keywords
        assert len(keywords) <= 5

class TestSafetyChecker:
    def test_local_safety_check(self):
        checker = SafetyChecker()
        
        # Safe content
        assert checker._local_safety_check(
            "Amazing AI tool", 
            "This tool helps with productivity", 
            ["politics"]
        ) == True
        
        # Banned term
        assert checker._local_safety_check(
            "Political news update", 
            "This covers politics", 
            ["politics"]
        ) == False
        
        # Spam indicators
        assert checker._local_safety_check(
            "Click here now", 
            "Link in bio for more click here", 
            []
        ) == False

    def test_validate_health_claims(self):
        checker = SafetyChecker()
        
        # Safe content
        assert checker.validate_health_claims(
            "This app helps you track workouts"
        ) == True
        
        # Health claim
        assert checker.validate_health_claims(
            "This supplement cures diabetes"
        ) == False

    def test_validate_financial_claims(self):
        checker = SafetyChecker()
        
        # Safe content
        assert checker.validate_financial_claims(
            "Learn about budgeting basics"
        ) == True
        
        # Financial claim
        assert checker.validate_financial_claims(
            "Guaranteed returns with this investment"
        ) == False

class TestPipeline:
    @pytest.mark.asyncio
    async def test_dry_run(self, mock_channel_config):
        with patch('orchestrator.pipeline.VideoGenerationPipeline._load_channels_config') as mock_load:
            mock_load.return_value = {"TestChannel": mock_channel_config}
            
            pipeline = VideoGenerationPipeline()
            
            # Mock the gatherer
            with patch('research.gather.TopicGatherer') as mock_gatherer_class:
                mock_gatherer = AsyncMock()
                mock_gatherer.__aenter__ = AsyncMock(return_value=mock_gatherer)
                mock_gatherer.__aexit__ = AsyncMock(return_value=None)
                mock_gatherer.gather_for_channel = AsyncMock(return_value=[
                    TopicIdea(
                        id="test_123",
                        seed_source=TopicSource.YT_TRENDING,
                        title="Test Topic",
                        angle="Test angle",
                        keywords=["test", "topic"],
                        score=0.8
                    )
                ])
                mock_gatherer_class.return_value = mock_gatherer
                
                # Mock script writer
                with patch.object(pipeline.script_writer, 'create_script_package') as mock_script:
                    from models.schemas import ScriptPackage
                    mock_script.return_value = ScriptPackage(
                        topic_id="test_123",
                        hook="Amazing test hook",
                        script_text="This is a test script with exactly eighty words to meet the minimum requirement for script length validation in our automated system. The script covers the topic comprehensively while maintaining engagement throughout the entire duration of the short-form video content piece.",
                        word_count=80,
                        title="Test Video Title",
                        description="Test description",
                        hashtags=["#test", "#shorts"]
                    )
                    
                    # Mock TTS
                    with patch.object(pipeline.edge_tts, 'generate_voiceover') as mock_tts:
                        from models.schemas import Voiceover
                        mock_tts.return_value = Voiceover(
                            path="/tmp/test.wav",
                            duration_sec=25.0,
                            voice_id="test-voice",
                            provider="edge-tts"
                        )
                        
                        result = await pipeline.dry_run("TestChannel")
                        
                        assert "error" not in result
                        assert result["channel"] == "TestChannel"
                        assert result["selected_topic"]["title"] == "Test Topic"
                        assert result["script"]["word_count"] == 80
                        assert result["voiceover"]["generated"] == True

    def test_pipeline_status(self):
        with patch('orchestrator.pipeline.VideoGenerationPipeline._load_channels_config') as mock_load:
            mock_load.return_value = {"TestChannel": {"name": "TestChannel"}}
            
            pipeline = VideoGenerationPipeline()
            status = pipeline.get_pipeline_status()
            
            assert "channels_configured" in status
            assert "available_channels" in status
            assert "tts_providers" in status
            assert "publishers" in status

class TestVideoComposition:
    def test_create_video_filter_complex(self):
        from video.compose import VideoComposer
        
        composer = VideoComposer()
        
        # Test with single video input
        filter_complex = composer._create_video_filter_complex(
            video_inputs=[2],
            render_spec=Mock(width=1080, height=1920),
            style={"background_color": "#1a1a1a"},
            duration=30.0
        )
        
        assert "scale=1080:1920" in filter_complex
        assert "crop=1080:1920" in filter_complex
        assert "zoompan" in filter_complex

    def test_create_caption_filter(self):
        from video.compose import VideoComposer
        
        composer = VideoComposer()
        
        caption_filter = composer._create_caption_filter(
            srt_path="/tmp/test.srt",
            style={
                "font_size": 72,
                "text_color": "#FFFFFF",
                "stroke_color": "#000000",
                "stroke_width": 2,
                "safe_margin": 180
            },
            render_spec=Mock(height=1920)
        )
        
        assert "subtitles=" in caption_filter
        assert "FontSize=72" in caption_filter
        assert "PrimaryColour=" in caption_filter

class TestCaptionGeneration:
    def test_split_into_segments(self):
        from assets.captions import CaptionGenerator
        
        generator = CaptionGenerator()
        
        text = "This is a test script. It has multiple sentences! Does it work properly?"
        segments = generator._split_into_segments(text)
        
        assert len(segments) > 1
        assert any("This is a test script." in segment for segment in segments)

    def test_calculate_timing(self):
        from assets.captions import CaptionGenerator
        from models.schemas import Voiceover
        
        generator = CaptionGenerator()
        
        segments = ["First segment", "Second segment", "Third segment"]
        timed_segments = generator._calculate_timing(segments, 30.0)
        
        assert len(timed_segments) == 3
        assert all(len(segment) == 3 for segment in timed_segments)  # text, start, end
        assert timed_segments[-1][2] <= 30.0  # Last segment ends within duration

    def test_format_timestamp(self):
        from assets.captions import CaptionGenerator
        
        generator = CaptionGenerator()
        
        timestamp = generator._format_timestamp(65.5)
        assert timestamp == "00:01:05,500"
        
        timestamp = generator._format_timestamp(3661.123)
        assert timestamp == "01:01:01,123"

# Integration test
class TestFullPipelineIntegration:
    @pytest.mark.asyncio
    async def test_research_to_script_flow(self, sample_topic_idea, mock_channel_config):
        """Test the flow from topic research to script generation"""
        
        # Test topic scoring
        scorer = TopicScorer()
        ranked_ideas = scorer.score_and_rank([sample_topic_idea], "TestChannel")
        
        assert len(ranked_ideas) == 1
        assert ranked_ideas[0].score > 0
        
        # Test safety checking
        checker = SafetyChecker()
        is_safe = checker._local_safety_check(
            sample_topic_idea.title,
            "This is a safe test script about technology",
            mock_channel_config["banned_terms"]
        )
        
        assert is_safe == True

if __name__ == "__main__":
    pytest.main([__file__, "-v"])