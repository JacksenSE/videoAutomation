# Auto Shorts - Production-Ready Video Generation Pipeline

A comprehensive automated system that researches trending topics, writes scripts, generates voiceovers, creates vertical videos with B-roll and captions, uploads to YouTube Shorts, and tracks performance analytics.

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- FFmpeg installed on system
- OpenAI API key
- YouTube API credentials
- Optional: Pexels API key for stock visuals

### Installation

1. **Clone and setup environment:**
```bash
git clone <repository>
cd auto-shorts
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

2. **Configure environment:**
```bash
cp .env.example .env
# Edit .env with your API keys and settings
```

3. **Initialize database:**
```bash
python -c "import asyncio; from models.db import create_tables; asyncio.run(create_tables())"
```

4. **Test components:**
```bash
python cli.py test-components
```

## 🔧 Configuration

### Environment Variables (.env)
```bash
# Required
OPENAI_API_KEY=your_openai_key
YOUTUBE_CLIENT_ID=your_youtube_client_id
YOUTUBE_CLIENT_SECRET=your_youtube_client_secret

# Optional
ELEVENLABS_API_KEY=your_elevenlabs_key  # For premium TTS
PEXELS_API_KEY=your_pexels_key         # For B-roll footage
ENABLE_TIKTOK=false                    # TikTok publishing (experimental)
```

### Channel Configuration (config/channels.json)
```json
[
  {
    "name": "ByteCult",
    "youtube_oauth_token": "tokens/bytecult.json",
    "niche": "tech news, AI tools, programming",
    "banned_terms": ["politics", "medical advice"],
    "local_time": "09:00",
    "style": "clean-bold"
  }
]
```

## 🎯 Usage

### Command Line Interface

**Run pipeline once:**
```bash
python cli.py run-once --channel ByteCult
```

**Dry run (no publishing):**
```bash
python cli.py run-once --channel ByteCult --dry-run
```

**Seed topic ideas:**
```bash
python cli.py seed-ideas --channel ByteCult --count 50
```

**Setup YouTube OAuth:**
```bash
python cli.py oauth-youtube --channel ByteCult
```

**Setup character assets:**
```bash
python cli.py setup-characters
```

**Schedule daily runs:**
```bash
python cli.py schedule --daily 09:00 --per-channel 1
```

**Get video metrics:**
```bash
python cli.py metrics --video-id YOUR_VIDEO_ID
```

### Web Interface

**Start the web server:**
```bash
python app.py
# Or: uvicorn app:app --host 0.0.0.0 --port 8000
```

**Access dashboard:**
- Main dashboard: http://localhost:8000
- Channel management: http://localhost:8000/channels
- Job monitoring: http://localhost:8000/jobs

### REST API

**Run pipeline once:**
```bash
curl -X POST "http://localhost:8000/run/once" \
  -H "Content-Type: application/json" \
  -d '{"channel": "ByteCult", "delay_minutes": 0}'
```

**Schedule daily runs:**
```bash
curl -X POST "http://localhost:8000/schedule/daily" \
  -H "Content-Type: application/json" \
  -d '{"hour": 9, "minute": 0, "per_channel": 1}'
```

**Get topic ideas:**
```bash
curl "http://localhost:8000/ideas?channel=ByteCult&limit=20"
```

## 🏗️ Architecture

### Core Components

1. **Research Module** (`research/`)
   - Gathers trending topics from YouTube, RSS feeds, Reddit
   - Scores topics based on novelty, momentum, and channel fit
   - Deduplicates and ranks ideas

2. **NLP Module** (`nlp/`)
   - Converts topics to outlines and scripts using OpenAI
   - Generates SEO-optimized titles, descriptions, hashtags
   - Safety filtering for banned terms and policy violations

3. **TTS Module** (`tts/`)
   - Edge TTS (free) for voiceover generation
   - ElevenLabs (premium) support with voice selection
   - SSML support for enhanced speech control

4. **Assets Module** (`assets/`)
   - B-roll fetching from Pexels API or local stock
   - Automatic caption generation with timing
   - Background music integration

5. **Video Composition** (`video/`)
   - FFmpeg-based video rendering
   - 9:16 aspect ratio optimization for Shorts
   - Enhanced visual composition with:
     - Gradient/solid color backgrounds
     - Automated title cards
     - Stock image/video integration
     - Character PNG overlays with pose switching
     - Comic-style speech bubbles
     - Background music integration

6. **Publishing** (`publish/`)
   - YouTube API integration with OAuth
   - Automatic Shorts categorization and optimization
   - Optional TikTok publishing (experimental)

7. **Analytics & Learning** (`analytics/`)
   - Performance tracking and metrics collection
   - Machine learning for topic scoring optimization
   - Keyword and hook performance analysis

### Pipeline Flow

```
Research → Script Generation → Voiceover → Asset Gathering → 
Video Composition → Publishing → Analytics Collection → Learning
```

## 💰 Cost Management

### Free Tier Usage
- **Edge TTS**: Completely free
- **YouTube API**: 10,000 requests/day free
- **OpenAI**: ~$0.01-0.05 per video
- **Total**: <$2/month for daily videos

### Paid Optimizations
- **ElevenLabs**: $5/month for premium voices
- **Pexels**: Free tier available, paid for more assets
- **Total with premium**: $5-15/month

### Cost Controls
- Set `MAX_DAILY_RUNS` to limit API usage
- Use local B-roll assets to avoid API costs
- Monitor OpenAI usage in dashboard

## 🔒 Security & Compliance

### Data Protection
- OAuth tokens stored locally in `tokens/` directory
- API keys in environment variables only
- No sensitive data in logs or database

### Platform Compliance
- YouTube: Uses official API only
- TikTok: Optional web automation (disabled by default)
- Content safety filtering for policy compliance

### Content Guidelines
- Banned terms filtering per channel
- Copyright risk detection
- Health/financial claims validation

## 📊 Monitoring & Analytics

### Performance Tracking
- View counts, engagement rates, retention metrics
- Topic performance correlation
- Hook effectiveness analysis
- Channel-specific insights

### Learning System
- Automatic topic scoring weight adjustment
- Keyword performance optimization
- Content structure recommendations
- Trend pattern recognition

## 🛠️ Customization

### Adding New Channels
1. Update `config/channels.json`
2. Set up YouTube OAuth: `python cli.py oauth-youtube --channel NewChannel`
3. Test with dry run: `python cli.py run-once --channel NewChannel --dry-run`

### Custom Characters
1. Add PNG files with transparent backgrounds to `data/assets/characters/`
2. Recommended size: 300x300 pixels or larger
3. Name descriptively (e.g., 'happy_character.png', 'thinking_character.png')
4. The system automatically cycles through available characters

### Background Music
1. Add royalty-free music files to `data/assets/music/`
2. Supported formats: MP3, WAV, M4A
3. Name files descriptively for automatic selection
4. System generates simple ambient music if none provided

### Custom Styles
Edit `config/styles.json` for enhanced visual customization:
```json
{
  "my-style": {
    "font_family": "Arial-Bold",
    "font_size": 88,
    "text_color": "#FFFFFF",
    "stroke_width": 3,
    "stroke_color": "#000000",
    "background_type": "gradient",
    "background_gradient": "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
    "title_font_size": 120,
    "character_size": 300,
    "character_position": "bottom-right",
    "speech_bubble_font_size": 48
  }
}
```

### Custom B-roll Sources
Extend `assets/broll.py` to add new providers:
```python
async def fetch_from_custom_api(self, keywords, count):
    # Your custom B-roll fetching logic
    pass
```

## 🐛 Troubleshooting

### Common Issues

**"No OAuth credentials found"**
- Run: `python cli.py oauth-youtube --channel YourChannel`
- Ensure YouTube API credentials are correct

**"FFmpeg not found"**
- Install FFmpeg: https://ffmpeg.org/download.html
- Ensure it's in your system PATH

**"OpenAI API quota exceeded"**
- Check your OpenAI usage dashboard
- Reduce `MAX_DAILY_RUNS` in .env

**"No topic ideas found"**
- Check internet connection
- Verify RSS feeds are accessible
- Try different niche keywords

### Debug Mode
```bash
export LOG_LEVEL=DEBUG
python cli.py run-once --channel YourChannel --dry-run
```

### Health Check
```bash
curl http://localhost:8000/health
```

## 📈 Scaling

### Multi-Channel Management
- Configure multiple channels in `channels.json`
- Each channel runs independently with its own schedule
- Shared learning across channels for better performance

### Performance Optimization
- Use local B-roll assets for faster rendering
- Implement Redis caching for topic ideas
- Scale with multiple worker processes

### Advanced Features
- A/B testing for hooks and thumbnails
- Trend memory to avoid repetitive content
- Webhook notifications for Discord/Slack
- Enhanced visual composition with characters and speech bubbles
- Automatic stock visual integration
- Dynamic background generation

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Submit a pull request

### Development Setup
```bash
pip install -r requirements.txt
pip install pytest black flake8
black .
flake8 .
pytest tests/
```

## 📄 License

MIT License - see LICENSE file for details.

## 🆘 Support

- GitHub Issues: Report bugs and feature requests
- Documentation: Check README and code comments
- Community: Join discussions in GitHub Discussions

---

**Auto Shorts v1.0** - Automated content creation for the modern creator economy.