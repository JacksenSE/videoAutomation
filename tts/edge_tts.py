import edge_tts
import asyncio
import os
import uuid
from typing import Optional
from models.schemas import Voiceover
from loguru import logger

class EdgeTTSProvider:
    def __init__(self, voice: str = "en-US-AriaNeural", rate: str = "+20%"):
        self.voice = voice
        self.rate = rate
        self.quality = "24khz_16bit_mono"

    async def generate_voiceover(
        self, 
        text: str, 
        output_dir: str = "./data/voice"
    ) -> Optional[Voiceover]:
        """Generate voiceover using Edge TTS"""
        try:
            # Ensure output directory exists
            os.makedirs(output_dir, exist_ok=True)
            
            # Generate unique filename
            filename = f"voice_{uuid.uuid4().hex}.wav"
            output_path = os.path.join(output_dir, filename)
            
            # Create TTS instance
            communicate = edge_tts.Communicate(text, self.voice, rate=self.rate)
            
            # Generate and save audio
            await communicate.save(output_path)
            
            # Get duration (approximate based on text length and rate)
            duration = self._estimate_duration(text)
            
            voiceover = Voiceover(
                path=output_path,
                duration_sec=duration,
                voice_id=self.voice,
                provider="edge-tts"
            )
            
            logger.info(f"Generated Edge TTS voiceover: {output_path} ({duration:.1f}s)")
            return voiceover
            
        except Exception as e:
            logger.error(f"Error generating Edge TTS voiceover: {e}")
            return None

    def _estimate_duration(self, text: str) -> float:
        """Estimate audio duration based on text length"""
        # Average speaking rate: ~150 words per minute for natural speech
        # With +20% rate increase: ~180 words per minute
        words = len(text.split())
        base_duration = (words / 180) * 60  # Convert to seconds
        
        # Add small buffer for pauses
        return base_duration + 1.0

    async def list_voices(self) -> list:
        """List available Edge TTS voices"""
        try:
            voices = await edge_tts.list_voices()
            return [
                {
                    'name': voice['Name'],
                    'gender': voice['Gender'],
                    'locale': voice['Locale'],
                    'suggested_codec': voice['SuggestedCodec']
                }
                for voice in voices
                if voice['Locale'].startswith('en-')  # English voices only
            ]
        except Exception as e:
            logger.error(f"Error listing Edge TTS voices: {e}")
            return []

    def get_voice_for_niche(self, niche: str) -> str:
        """Get appropriate voice for specific niche"""
        niche_lower = niche.lower()
        
        voice_mapping = {
            'tech': 'en-US-AriaNeural',      # Professional female
            'ai': 'en-US-ChristopherNeural',  # Professional male
            'finance': 'en-US-JennyNeural',   # Authoritative female
            'meditation': 'en-US-AmberNeural', # Calm female
            'culture': 'en-US-AshleyNeural',  # Engaging female
            'entertainment': 'en-US-CoraNeural' # Energetic female
        }
        
        for key, voice in voice_mapping.items():
            if key in niche_lower:
                return voice
        
        return self.voice  # Default voice

    async def test_voice_quality(self, text: str = "This is a test of the voice quality.") -> bool:
        """Test if Edge TTS is working properly"""
        try:
            test_voiceover = await self.generate_voiceover(text, "/tmp")
            if test_voiceover and os.path.exists(test_voiceover.path):
                # Clean up test file
                os.remove(test_voiceover.path)
                return True
            return False
        except Exception as e:
            logger.error(f"Edge TTS test failed: {e}")
            return False

    async def generate_with_ssml(self, ssml_text: str, output_dir: str = "./data/voice") -> Optional[Voiceover]:
        """Generate voiceover with SSML markup for better control"""
        try:
            os.makedirs(output_dir, exist_ok=True)
            filename = f"voice_ssml_{uuid.uuid4().hex}.wav"
            output_path = os.path.join(output_dir, filename)
            
            # Wrap in basic SSML structure if not already
            if not ssml_text.strip().startswith('<speak>'):
                ssml_text = f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">{ssml_text}</speak>'
            
            communicate = edge_tts.Communicate(ssml_text, self.voice, rate=self.rate)
            await communicate.save(output_path)
            
            # Estimate duration from plain text (strip SSML tags)
            import re
            plain_text = re.sub(r'<[^>]+>', '', ssml_text)
            duration = self._estimate_duration(plain_text)
            
            return Voiceover(
                path=output_path,
                duration_sec=duration,
                voice_id=self.voice,
                provider="edge-tts"
            )
            
        except Exception as e:
            logger.error(f"Error generating SSML voiceover: {e}")
            return None

    def create_emphasized_ssml(self, script: str, hook: str) -> str:
        """Create SSML with emphasis on hook and key phrases"""
        # Emphasize the hook if it appears in the script
        if hook in script:
            script = script.replace(hook, f'<emphasis level="strong">{hook}</emphasis>')
        
        # Add pauses for better pacing
        script = script.replace('. ', '.<break time="300ms"/> ')
        script = script.replace('! ', '!<break time="400ms"/> ')
        script = script.replace('? ', '?<break time="400ms"/> ')
        
        # Add prosody for engagement
        return f'<prosody rate="{self.rate}" pitch="+5%">{script}</prosody>'