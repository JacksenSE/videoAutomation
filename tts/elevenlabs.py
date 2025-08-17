import os
import uuid
import aiohttp
from typing import Optional
from models.schemas import Voiceover
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

class ElevenLabsProvider:
    def __init__(self, api_key: Optional[str] = None, voice_id: str = "21m00Tcm4TlvDq8ikWAM"):
        self.api_key = api_key or os.getenv("ELEVENLABS_API_KEY")
        self.voice_id = voice_id  # Default: Rachel voice
        self.base_url = "https://api.elevenlabs.io/v1"
        
        if not self.api_key:
            logger.warning("ElevenLabs API key not found - provider will be unavailable")

    async def generate_voiceover(
        self, 
        text: str, 
        output_dir: str = "./data/voice",
        voice_settings: Optional[dict] = None
    ) -> Optional[Voiceover]:
        """Generate voiceover using ElevenLabs API"""
        if not self.api_key:
            logger.error("ElevenLabs API key not available")
            return None

        try:
            os.makedirs(output_dir, exist_ok=True)
            
            filename = f"voice_elevenlabs_{uuid.uuid4().hex}.wav"
            output_path = os.path.join(output_dir, filename)
            
            # Default voice settings optimized for shorts
            if not voice_settings:
                voice_settings = {
                    "stability": 0.75,
                    "similarity_boost": 0.75,
                    "style": 0.5,
                    "use_speaker_boost": True
                }
            
            url = f"{self.base_url}/text-to-speech/{self.voice_id}"
            
            headers = {
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
                "xi-api-key": self.api_key
            }
            
            data = {
                "text": text,
                "model_id": "eleven_monolingual_v1",
                "voice_settings": voice_settings
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=data, headers=headers) as response:
                    if response.status == 200:
                        audio_data = await response.read()
                        
                        # Save audio file
                        with open(output_path, 'wb') as f:
                            f.write(audio_data)
                        
                        # Estimate duration (ElevenLabs doesn't provide duration directly)
                        duration = self._estimate_duration(text)
                        
                        voiceover = Voiceover(
                            path=output_path,
                            duration_sec=duration,
                            voice_id=self.voice_id,
                            provider="elevenlabs"
                        )
                        
                        logger.info(f"Generated ElevenLabs voiceover: {output_path} ({duration:.1f}s)")
                        return voiceover
                    
                    else:
                        error_text = await response.text()
                        logger.error(f"ElevenLabs API error {response.status}: {error_text}")
                        return None
        
        except Exception as e:
            logger.error(f"Error generating ElevenLabs voiceover: {e}")
            return None

    def _estimate_duration(self, text: str) -> float:
        """Estimate audio duration based on text length"""
        # ElevenLabs speaks at roughly 160-180 WPM for natural speech
        words = len(text.split())
        base_duration = (words / 170) * 60  # Convert to seconds
        return base_duration + 0.5  # Small buffer

    async def list_voices(self) -> list:
        """List available ElevenLabs voices"""
        if not self.api_key:
            return []
        
        try:
            url = f"{self.base_url}/voices"
            headers = {"xi-api-key": self.api_key}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return [
                            {
                                'voice_id': voice['voice_id'],
                                'name': voice['name'],
                                'category': voice['category'],
                                'description': voice.get('description', ''),
                                'accent': voice.get('labels', {}).get('accent', ''),
                                'age': voice.get('labels', {}).get('age', ''),
                                'gender': voice.get('labels', {}).get('gender', '')
                            }
                            for voice in data.get('voices', [])
                        ]
                    else:
                        logger.error(f"Failed to list ElevenLabs voices: {response.status}")
                        return []
        
        except Exception as e:
            logger.error(f"Error listing ElevenLabs voices: {e}")
            return []

    def get_voice_for_niche(self, niche: str) -> str:
        """Get appropriate voice ID for specific niche"""
        niche_lower = niche.lower()
        
        # Map niches to ElevenLabs voice IDs (these are example IDs)
        voice_mapping = {
            'tech': "21m00Tcm4TlvDq8ikWAM",      # Rachel - clear, professional
            'ai': "AZnzlk1XvdvUeBnXmlld",        # Domi - tech-savvy
            'finance': "EXAVITQu4vr4xnSDxMaL",   # Bella - authoritative
            'meditation': "ThT5KcBeYPX3keUQqHPh", # Dorothy - calm
            'culture': "pNInz6obpgDQGcFmaJgB",    # Adam - engaging
            'entertainment': "TxGEqnHWrfWFTfGW9XjX" # Josh - energetic
        }
        
        for key, voice_id in voice_mapping.items():
            if key in niche_lower:
                return voice_id
        
        return self.voice_id  # Default voice

    async def clone_voice_from_sample(self, name: str, files: list) -> Optional[str]:
        """Clone a voice from audio samples (premium feature)"""
        if not self.api_key:
            return None
        
        try:
            url = f"{self.base_url}/voices/add"
            headers = {"xi-api-key": self.api_key}
            
            # This would require multipart form data for file upload
            # Implementation depends on specific requirements
            logger.info(f"Voice cloning requested for: {name}")
            # Placeholder - actual implementation would upload files
            return None
            
        except Exception as e:
            logger.error(f"Error cloning voice: {e}")
            return None

    async def test_api_connection(self) -> bool:
        """Test ElevenLabs API connection"""
        if not self.api_key:
            return False
        
        try:
            url = f"{self.base_url}/voices"
            headers = {"xi-api-key": self.api_key}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    return response.status == 200
        
        except Exception as e:
            logger.error(f"ElevenLabs API test failed: {e}")
            return False

    async def get_character_count(self) -> Optional[dict]:
        """Get remaining character count for the subscription"""
        if not self.api_key:
            return None
        
        try:
            url = f"{self.base_url}/user/subscription"
            headers = {"xi-api-key": self.api_key}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            'character_count': data.get('character_count', 0),
                            'character_limit': data.get('character_limit', 0),
                            'can_extend_character_limit': data.get('can_extend_character_limit', False)
                        }
        
        except Exception as e:
            logger.error(f"Error getting character count: {e}")
            return None