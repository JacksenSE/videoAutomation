import os
import re
import math
from typing import List, Tuple
from models.schemas import ScriptPackage, Voiceover
from loguru import logger

class CaptionGenerator:
    def __init__(self):
        self.words_per_line = 6
        self.max_chars_per_line = 40
        self.words_per_second = 3.0  # Average speaking rate

    def generate_srt(
        self, 
        script: str, 
        voiceover: Voiceover, 
        output_dir: str = "./data/renders"
    ) -> str:
        """Generate SRT caption file from script and voiceover timing"""
        try:
            os.makedirs(output_dir, exist_ok=True)
            
            # Clean script text
            clean_script = self._clean_script_text(script)
            
            # Split into caption segments
            segments = self._split_into_segments(clean_script)
            
            # Calculate timing for each segment
            timed_segments = self._calculate_timing(segments, voiceover.duration_sec)
            
            # Generate SRT content
            srt_content = self._generate_srt_content(timed_segments)
            
            # Save to file
            srt_filename = f"captions_{hash(script) % 10000}.srt"
            srt_path = os.path.join(output_dir, srt_filename)
            
            with open(srt_path, 'w', encoding='utf-8') as f:
                f.write(srt_content)
            
            logger.info(f"Generated SRT captions: {srt_path}")
            return srt_path
        
        except Exception as e:
            logger.error(f"Error generating SRT captions: {e}")
            return ""

    def _clean_script_text(self, script: str) -> str:
        """Clean script text for caption generation"""
        # Remove extra whitespace
        script = re.sub(r'\s+', ' ', script.strip())
        
        # Fix common punctuation issues
        script = re.sub(r'\s+([.!?])', r'\1', script)
        script = re.sub(r'([.!?])\s*([A-Z])', r'\1 \2', script)
        
        return script

    def _split_into_segments(self, text: str) -> List[str]:
        """Split text into caption segments"""
        words = text.split()
        segments = []
        current_segment = []
        
        for word in words:
            current_segment.append(word)
            
            # Check if we should break the segment
            segment_text = ' '.join(current_segment)
            
            # Break on punctuation with good length
            if (len(current_segment) >= 4 and 
                word.endswith(('.', '!', '?')) and 
                len(segment_text) <= self.max_chars_per_line):
                segments.append(segment_text)
                current_segment = []
            
            # Break on max words per line
            elif len(current_segment) >= self.words_per_line:
                segments.append(segment_text)
                current_segment = []
            
            # Break on max characters
            elif len(segment_text) >= self.max_chars_per_line:
                if len(current_segment) > 1:
                    # Keep last word for next segment
                    segments.append(' '.join(current_segment[:-1]))
                    current_segment = [current_segment[-1]]
                else:
                    # Single long word - keep as is
                    segments.append(segment_text)
                    current_segment = []
        
        # Add remaining words
        if current_segment:
            segments.append(' '.join(current_segment))
        
        return segments

    def _calculate_timing(self, segments: List[str], total_duration: float) -> List[Tuple[str, float, float]]:
        """Calculate start and end times for each segment"""
        timed_segments = []
        
        # Calculate words per segment for timing distribution
        segment_word_counts = [len(segment.split()) for segment in segments]
        total_words = sum(segment_word_counts)
        
        if total_words == 0:
            return timed_segments
        
        current_time = 0.0
        
        for i, (segment, word_count) in enumerate(zip(segments, segment_word_counts)):
            # Calculate segment duration based on word count
            segment_duration = (word_count / total_words) * total_duration
            
            # Minimum duration of 1 second per segment
            segment_duration = max(1.0, segment_duration)
            
            # Adjust for natural speech pauses
            if segment.endswith(('.', '!', '?')):
                segment_duration += 0.3  # Pause after sentences
            elif segment.endswith(','):
                segment_duration += 0.1  # Brief pause after commas
            
            start_time = current_time
            end_time = current_time + segment_duration
            
            timed_segments.append((segment, start_time, end_time))
            current_time = end_time
        
        # Normalize to fit within total duration
        if current_time > total_duration:
            scale_factor = total_duration / current_time
            normalized_segments = []
            
            for segment, start, end in timed_segments:
                normalized_segments.append((
                    segment,
                    start * scale_factor,
                    end * scale_factor
                ))
            
            return normalized_segments
        
        return timed_segments

    def _generate_srt_content(self, timed_segments: List[Tuple[str, float, float]]) -> str:
        """Generate SRT format content"""
        srt_content = []
        
        for i, (segment, start_time, end_time) in enumerate(timed_segments, 1):
            # Format timestamps
            start_ts = self._format_timestamp(start_time)
            end_ts = self._format_timestamp(end_time)
            
            # Add SRT entry
            srt_content.append(f"{i}")
            srt_content.append(f"{start_ts} --> {end_ts}")
            srt_content.append(segment)
            srt_content.append("")  # Empty line between entries
        
        return "\n".join(srt_content)

    def _format_timestamp(self, seconds: float) -> str:
        """Format seconds as SRT timestamp (HH:MM:SS,mmm)"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        milliseconds = int((seconds % 1) * 1000)
        
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"

    def generate_word_level_srt(
        self, 
        script: str, 
        voiceover: Voiceover, 
        output_dir: str = "./data/renders"
    ) -> str:
        """Generate word-level SRT for more precise timing"""
        try:
            os.makedirs(output_dir, exist_ok=True)
            
            words = self._clean_script_text(script).split()
            total_duration = voiceover.duration_sec
            
            # Estimate timing per word
            words_per_second = len(words) / total_duration
            
            timed_words = []
            current_time = 0.0
            
            for word in words:
                # Base duration per word
                word_duration = 1.0 / words_per_second
                
                # Adjust for word length and punctuation
                word_duration *= (len(word) / 5.0)  # Longer words take more time
                word_duration = max(0.2, min(2.0, word_duration))  # Clamp between 0.2-2 seconds
                
                # Add pauses for punctuation
                if word.endswith(('.', '!', '?')):
                    word_duration += 0.4
                elif word.endswith(','):
                    word_duration += 0.2
                
                start_time = current_time
                end_time = current_time + word_duration
                
                timed_words.append((word, start_time, end_time))
                current_time = end_time
            
            # Normalize to fit total duration
            if current_time > total_duration:
                scale_factor = total_duration / current_time
                timed_words = [
                    (word, start * scale_factor, end * scale_factor)
                    for word, start, end in timed_words
                ]
            
            # Generate SRT content
            srt_content = []
            for i, (word, start_time, end_time) in enumerate(timed_words, 1):
                start_ts = self._format_timestamp(start_time)
                end_ts = self._format_timestamp(end_time)
                
                srt_content.append(f"{i}")
                srt_content.append(f"{start_ts} --> {end_ts}")
                srt_content.append(word)
                srt_content.append("")
            
            srt_filename = f"word_captions_{hash(script) % 10000}.srt"
            srt_path = os.path.join(output_dir, srt_filename)
            
            with open(srt_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(srt_content))
            
            logger.info(f"Generated word-level SRT captions: {srt_path}")
            return srt_path
        
        except Exception as e:
            logger.error(f"Error generating word-level SRT: {e}")
            return ""

    def create_hook_highlight_srt(
        self, 
        script: str, 
        hook: str, 
        voiceover: Voiceover,
        output_dir: str = "./data/renders"
    ) -> str:
        """Create SRT with special formatting for hook text"""
        try:
            # Find hook in script
            hook_start = script.lower().find(hook.lower())
            if hook_start == -1:
                return self.generate_srt(script, voiceover, output_dir)
            
            # Generate regular SRT first
            regular_srt_path = self.generate_srt(script, voiceover, output_dir)
            
            # Read and modify SRT to highlight hook
            with open(regular_srt_path, 'r', encoding='utf-8') as f:
                srt_content = f.read()
            
            # Add formatting to hook text
            formatted_hook = f"<b><i>{hook}</i></b>"
            srt_content = srt_content.replace(hook, formatted_hook)
            
            # Save highlighted version
            highlight_filename = f"hook_captions_{hash(script) % 10000}.srt"
            highlight_path = os.path.join(output_dir, highlight_filename)
            
            with open(highlight_path, 'w', encoding='utf-8') as f:
                f.write(srt_content)
            
            logger.info(f"Generated hook-highlighted SRT: {highlight_path}")
            return highlight_path
        
        except Exception as e:
            logger.error(f"Error generating hook-highlighted SRT: {e}")
            return self.generate_srt(script, voiceover, output_dir)

    def validate_srt_timing(self, srt_path: str, max_duration: float) -> bool:
        """Validate SRT file timing doesn't exceed video duration"""
        try:
            with open(srt_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Find all timestamps
            timestamp_pattern = r'(\d{2}:\d{2}:\d{2},\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2},\d{3})'
            matches = re.findall(timestamp_pattern, content)
            
            if not matches:
                return False
            
            # Check last end timestamp
            last_end = matches[-1][1]
            last_seconds = self._parse_timestamp(last_end)
            
            return last_seconds <= max_duration
        
        except Exception as e:
            logger.error(f"Error validating SRT timing: {e}")
            return False

    def _parse_timestamp(self, timestamp: str) -> float:
        """Parse SRT timestamp to seconds"""
        try:
            time_part, ms_part = timestamp.split(',')
            h, m, s = map(int, time_part.split(':'))
            ms = int(ms_part)
            
            return h * 3600 + m * 60 + s + ms / 1000.0
        except Exception:
            return 0.0