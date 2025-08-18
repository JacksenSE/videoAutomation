import os
import subprocess
import json
import uuid
from typing import List, Optional, Dict
from models.schemas import AssetBundle, RenderSpec, RenderResult, Voiceover
from loguru import logger


class VideoComposer:
    def __init__(self, styles_config: str = "./config/styles.json"):
        self.styles_config = styles_config
        self.load_styles()
        self.temp_dir = "./data/temp"
        self.characters_dir = "./data/assets/characters"
        self.speech_bubbles_dir = "./data/assets/speech_bubbles"
        os.makedirs(self.temp_dir, exist_ok=True)
        os.makedirs(self.characters_dir, exist_ok=True)
        os.makedirs(self.speech_bubbles_dir, exist_ok=True)
        logger.info(f"VideoComposer loaded from {__file__}")

    # ---------- Styles ----------

    def load_styles(self):
        """Load video style configurations"""
        try:
            if os.path.exists(self.styles_config):
                with open(self.styles_config, 'r') as f:
                    self.styles = json.load(f)
            else:
                self.styles = self._get_default_styles()
                logger.warning("Styles config not found, using defaults")
        except Exception as e:
            logger.error(f"Error loading styles: {e}")
            self.styles = self._get_default_styles()

    def _get_default_styles(self) -> Dict:
        """Get default video styles with character support"""
        return {
            "clean-bold": {
                "font_family": "Arial-Bold",
                "font_size": 72,
                "text_color": "#FFFFFF",
                "stroke_width": 3,
                "stroke_color": "#000000",
                "caption_position": "center-bottom",
                "safe_margin": 200,
                "hook_font_size": 88,

                "background_type": "gradient",
                "background_color": "#1a1a1a",
                "background_gradient": "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",

                "title_font_size": 80,
                "title_position": "top-center",
                "title_margin": 60,

                "character_size": 600,
                "character_position": "bottom-right",
                "character_margin": 50,

                "speech_bubble_font_size": 44,
                "speech_bubble_color": "#FFFFFF",
                "speech_bubble_stroke": "#000000"
            },
            "creator-minimal": {
                "font_family": "Arial",
                "font_size": 64,
                "text_color": "#FFFFFF",
                "stroke_width": 2,
                "stroke_color": "#333333",
                "caption_position": "center-bottom",
                "safe_margin": 180,
                "hook_font_size": 80,

                "background_type": "solid",
                "background_color": "#2d2d2d",

                "title_font_size": 72,
                "title_position": "top-center",
                "title_margin": 80,

                "character_size": 500,
                "character_position": "bottom-left",
                "character_margin": 40,

                "speech_bubble_font_size": 40,
                "speech_bubble_color": "#FFFFFF",
                "speech_bubble_stroke": "#333333"
            }
        }

    # ---------- Public API ----------

    async def compose_video(
        self,
        voiceover: Voiceover,
        assets: AssetBundle,
        render_spec: RenderSpec,
        script_package=None,
        output_dir: str = "./data/renders"
    ) -> Optional[RenderResult]:
        """Compose final video with enhanced visual elements (simple anchors)"""
        try:
            os.makedirs(output_dir, exist_ok=True)
            output_filename = f"video_{uuid.uuid4().hex}.mp4"
            output_path = os.path.join(output_dir, output_filename)
            style = self.styles.get(render_spec.style, self.styles["clean-bold"])

            # Generate character sequence and speech bubbles
            character_sequence = self._generate_character_sequence(voiceover.duration_sec, style)
            speech_bubbles = self._generate_speech_bubbles(script_package, voiceover.duration_sec) if script_package else []

            success = await self._compose_enhanced_video(
                voiceover, assets, render_spec, style, output_path,
                script_package, character_sequence, speech_bubbles
            )

            if success:
                thumb_path = await self._generate_thumbnail(output_path, output_dir)
                file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
                result = RenderResult(
                    path=output_path,
                    thumb_path=thumb_path,
                    duration_sec=voiceover.duration_sec,
                    file_size_mb=round(file_size_mb, 2)
                )
                logger.info(f"Enhanced video composed successfully: {output_path} ({file_size_mb:.1f}MB)")
                return result
            return None
        except Exception as e:
            logger.error(f"Error composing enhanced video: {e}")
            return None

    # ---------- FFmpeg pipeline ----------

    async def _compose_enhanced_video(
        self,
        voiceover: Voiceover,
        assets: AssetBundle,
        render_spec: RenderSpec,
        style: Dict,
        output_path: str,
        script_package=None,
        character_sequence: List[Dict] = None,
        speech_bubbles: List[Dict] = None
    ) -> bool:
        """Compose video with background, title, optional stock clip, character overlays, optional bubbles"""
        try:
            logger.info("VideoComposer::_compose_enhanced_video")

            cmd = ['ffmpeg', '-y']
            filter_complex_parts: List[str] = []

            # Input 0: Audio (voiceover)
            cmd.extend(['-i', voiceover.path])
            input_index = 1

            # Input 1: Optional background music (not mixed here; kept simple)
            music_exists = False
            if assets.music_path and os.path.exists(assets.music_path):
                cmd.extend(['-i', assets.music_path])
                music_exists = True
                input_index += 1

            # Create background
            bg_filter = self._create_background_filter(render_spec, style, voiceover.duration_sec)
            filter_complex_parts.append(bg_filter)
            current_video_label = "[bg]"

            # Title card
            if script_package and getattr(script_package, "title", None):
                title_filter = self._create_title_filter(
                    script_package.title, style, render_spec, current_video_label
                )
                filter_complex_parts.append(title_filter)
                current_video_label = "[titled]"

            # Stock visual (single clip in the middle band)
            stock_visual_index = None
            if assets.video_clips and len(assets.video_clips) > 0:
                stock_path = assets.video_clips[0]
                if os.path.exists(stock_path):
                    cmd.extend(['-i', stock_path])
                    stock_visual_index = input_index
                    input_index += 1

                    stock_filter = self._create_stock_visual_filter(
                        stock_visual_index, style, render_spec, current_video_label
                    )
                    filter_complex_parts.append(stock_filter)
                    current_video_label = "[with_stock]"

            # Character sequence (simple anchors: bottom-left/right/center with margin)
            if character_sequence:
                for i, char_info in enumerate(character_sequence):
                    if os.path.exists(char_info['path']):
                        cmd.extend(['-i', char_info['path']])
                        char_input_index = input_index
                        input_index += 1

                        char_filter = self._create_character_filter(
                            char_input_index, char_info, style, render_spec, current_video_label, i
                        )
                        filter_complex_parts.append(char_filter)
                        current_video_label = f"[with_char_{i}]"

            # Speech bubbles (optional)
            if speech_bubbles:
                for i, bubble in enumerate(speech_bubbles):
                    bubble_filter = self._create_speech_bubble_filter(
                        bubble, style, render_spec, current_video_label, i
                    )
                    filter_complex_parts.append(bubble_filter)
                    current_video_label = f"[with_bubble_{i}]"

            # Audio mapping (no background music mix to keep this simple)
            filter_complex_parts.append("[0:a]anull[audio]")

            # Assemble filter_complex
            if filter_complex_parts:
                fc = ';'.join(filter_complex_parts)
                cmd.extend(['-filter_complex', fc])

            # Map outputs
            cmd.extend(['-map', current_video_label])
            cmd.extend(['-map', '[audio]'])

            # Output settings
            cmd.extend([
                '-c:v', 'libx264',
                '-preset', 'medium',
                '-crf', '23',
                '-pix_fmt', 'yuv420p',
                '-c:a', 'aac',
                '-b:a', '128k',
                '-r', str(render_spec.fps),
                '-t', str(voiceover.duration_sec),
                output_path
            ])

            logger.debug("Enhanced FFMPEG CMD:\n" + " ".join(cmd))
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

            if result.returncode == 0:
                logger.info("Enhanced FFmpeg composition completed successfully")
                return True
            else:
                logger.error(f"Enhanced FFmpeg error: {result.stderr}")
                return False

        except Exception as e:
            logger.error(f"Error in enhanced FFmpeg composition: {e}")
            return False

    # ---------- Filter builders (simple anchors) ----------

    def _create_background_filter(self, render_spec: RenderSpec, style: Dict, duration: float) -> str:
        """Create background filter (solid color or a basic gradient)"""
        W, H = render_spec.width, render_spec.height
        bg_type = style.get('background_type', 'solid')

        if bg_type == 'gradient':
            # simple two-color gradient approximation
            gradient_colors = style.get(
                'background_gradient',
                'linear-gradient(135deg, #667eea 0%, #764ba2 100%)'
            )
            if '#667eea' in gradient_colors and '#764ba2' in gradient_colors:
                return (f"color=c=#667eea:s={W}x{H}:d={duration},"
                        f"geq=r='255*((1-Y/{H})*0.4+Y/{H}*0.46)':"
                        f"g='255*((1-Y/{H})*0.5+Y/{H}*0.27)':"
                        f"b='255*((1-Y/{H})*0.92+Y/{H}*0.64)'[bg]")
            # fallback solid if unrecognized gradient
            bg_color = style.get('background_color', '#1a1a1a')
            return f"color=c={bg_color}:s={W}x{H}:d={duration}[bg]"
        else:
            bg_color = style.get('background_color', '#1a1a1a')
            return f"color=c={bg_color}:s={W}x{H}:d={duration}[bg]"

    def _create_title_filter(self, title: str, style: Dict, render_spec: RenderSpec, input_label: str) -> str:
        """Create title overlay (centered horizontally, fixed margin from top)"""
        font_size = int(style.get('title_font_size', 80))
        margin = int(style.get('title_margin', 60))
        text_color = style.get('text_color', '#FFFFFF')
        stroke_color = style.get('stroke_color', '#000000')
        stroke_width = int(style.get('stroke_width', 3))

        clean_title = self._escape_drawtext_text(title)[:80]
        enable_expr = "between(t\\,0\\,3)"  # show first 3s

        return (
            f"{input_label}drawtext="
            f"text='{clean_title}':"
            f"fontsize={font_size}:fontcolor={text_color}:"
            f"borderw={stroke_width}:bordercolor={stroke_color}:"
            f"x=(w-text_w)/2:y={margin}:enable='{enable_expr}'[titled]"
        )

    def _create_stock_visual_filter(self, stock_index: int, style: Dict, render_spec: RenderSpec, input_label: str) -> str:
        """Overlay a stock clip or image in a centered horizontal band"""
        W, H = render_spec.width, render_spec.height
        visual_height = 600  # fixed band height
        visual_y = (H - visual_height) // 2

        return (
            f"[{stock_index}:v]scale={W}:{visual_height}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{visual_height}:(ow-iw)/2:(oh-ih)/2:black[stock_scaled];"
            f"{input_label}[stock_scaled]overlay=0:{visual_y}:enable='between(t,1,25)'[with_stock]"
        )

    def _create_character_filter(self, char_index: int, char_info: Dict, style: Dict,
                                 render_spec: RenderSpec, input_label: str, sequence_num: int) -> str:
        """Create character overlay (simple anchor only)"""
        char_size = int(style.get('character_size', 600))
        margin = int(style.get('character_margin', 50))
        position = (style.get('character_position', 'bottom-right') or 'bottom-right').lower()

        # Compute anchor position
        if position == 'bottom-right':
            x_pos = f"W-{char_size}-{margin}"
            y_pos = f"H-{char_size}-{margin}"
        elif position == 'bottom-left':
            x_pos = f"{margin}"
            y_pos = f"H-{char_size}-{margin}"
        else:  # bottom-center
            x_pos = f"(W-{char_size})/2"
            y_pos = f"H-{char_size}-{margin}"

        start_time = char_info['start_time']
        end_time = char_info['end_time']

        return (
            f"[{char_index}:v]scale={char_size}:{char_size}:force_original_aspect_ratio=decrease[char_{sequence_num}];"
            f"{input_label}[char_{sequence_num}]overlay={x_pos}:{y_pos}:enable='between(t,{start_time},{end_time})'[with_char_{sequence_num}]"
        )

    def _create_speech_bubble_filter(self, bubble: Dict, style: Dict, render_spec: RenderSpec, input_label: str, bubble_num: int) -> str:
        """Create speech bubble overlay centered horizontally above character area"""
        font_size = int(style.get('speech_bubble_font_size', 44))
        bubble_color = style.get('speech_bubble_color', '#FFFFFF')
        stroke_color = style.get('speech_bubble_stroke', '#000000')

        text = self._escape_drawtext_text(bubble['text'])[:50]
        start_time = bubble['start_time']
        end_time = bubble['end_time']

        char_margin = int(style.get('character_margin', 50))
        char_size = int(style.get('character_size', 600))
        bubble_y = render_spec.height - char_size - char_margin - 150  # above character box

        return (
            f"{input_label}drawtext=text='{text}':"
            f"fontsize={font_size}:fontcolor={bubble_color}:"
            f"borderw=2:bordercolor={stroke_color}:"
            f"box=1:boxcolor=white@0.8:boxborderw=5:"
            f"x=(w-text_w)/2:y={bubble_y}:enable='between(t,{start_time},{end_time})'[with_bubble_{bubble_num}]"
        )

    # ---------- Helpers ----------

    @staticmethod
    def _escape_drawtext_text(s: str) -> str:
        """
        Escape text for use in FFmpeg drawtext's text=... value.
        We escape backslash, colon, percent, single-quote, brackets, equals, and commas.
        """
        if not s:
            return ""
        s = s.replace('\\', r'\\')
        s = s.replace(':',  r'\:')
        s = s.replace('%',  r'\%')
        s = s.replace("'",  r"\'")
        s = s.replace('[',  r'\[').replace(']', r'\]')
        s = s.replace('=',  r'\=')
        s = s.replace(',',  r'\,')
        return s

    def _generate_character_sequence(self, duration: float, style: Dict) -> List[Dict]:
        """Generate sequence of character poses throughout the video (up to 4)"""
        character_sequence = []

        character_files = self._get_character_files()
        if not character_files:
            character_files = self._create_default_characters()

        num_segments = min(4, max(1, len(character_files)))
        segment_duration = duration / num_segments

        for i in range(num_segments):
            char_file = character_files[i % len(character_files)]
            character_sequence.append({
                'path': char_file,
                'start_time': i * segment_duration,
                'end_time': (i + 1) * segment_duration,
                'pose': f'pose_{i + 1}'
            })

        return character_sequence

    def _generate_speech_bubbles(self, script_package, duration: float) -> List[Dict]:
        """Generate speech bubbles from script content"""
        if not script_package:
            return []

        bubbles = []
        script_text = getattr(script_package, "script_text", "") or ""

        sentences = [s.strip() for s in script_text.split('.') if s.strip()]
        key_phrases = []
        for sentence in sentences[:3]:  # max 3 bubbles
            if 10 < len(sentence) < 50 and any(
                w in sentence.lower() for w in ['amazing', 'incredible', 'wow', 'new', 'breakthrough', 'discover']
            ):
                key_phrases.append(sentence)

        if key_phrases:
            bubble_duration = 3.0
            interval = max(5.0, duration / len(key_phrases))
            for i, phrase in enumerate(key_phrases):
                start_time = i * interval + 2
                end_time = min(start_time + bubble_duration, duration - 1)
                bubbles.append({
                    'text': phrase,
                    'start_time': start_time,
                    'end_time': end_time
                })

        return bubbles

    def _get_character_files(self) -> List[str]:
        """Get available character PNG files"""
        character_files = []
        if os.path.exists(self.characters_dir):
            for filename in os.listdir(self.characters_dir):
                if filename.lower().endswith('.png'):
                    character_files.append(os.path.join(self.characters_dir, filename))
        return character_files

    def _create_default_characters(self) -> List[str]:
        """Create simple colored square placeholders via FFmpeg"""
        default_characters = []
        character_configs = [
            {'color': '#4A90E2', 'name': 'character_1.png'},
            {'color': '#7ED321', 'name': 'character_2.png'},
            {'color': '#F5A623', 'name': 'character_3.png'},
            {'color': '#D0021B', 'name': 'character_4.png'}
        ]
        for config in character_configs:
            char_path = os.path.join(self.characters_dir, config['name'])
            if not os.path.exists(char_path):
                try:
                    cmd = [
                        'ffmpeg', '-y',
                        '-f', 'lavfi',
                        '-i', f'color=c={config["color"]}:s=300x300:d=1',
                        '-vf', 'format=rgba',
                        '-frames:v', '1',
                        char_path
                    ]
                    subprocess.run(cmd, capture_output=True)
                    if os.path.exists(char_path):
                        default_characters.append(char_path)
                        logger.info(f"Created default character: {config['name']}")
                except Exception as e:
                    logger.error(f"Error creating default character: {e}")
            else:
                default_characters.append(char_path)
        return default_characters

    async def _generate_thumbnail(self, video_path: str, output_dir: str) -> str:
        """Generate thumbnail from video"""
        try:
            thumb_filename = f"thumb_{uuid.uuid4().hex}.jpg"
            thumb_path = os.path.join(output_dir, thumb_filename)
            cmd = [
                'ffmpeg', '-y',
                '-i', video_path,
                '-ss', '00:00:05',
                '-vframes', '1',
                '-q:v', '2',
                thumb_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                logger.info(f"Generated thumbnail: {thumb_path}")
                return thumb_path
            else:
                logger.error(f"Error generating thumbnail: {result.stderr}")
                return ""
        except Exception as e:
            logger.error(f"Error generating thumbnail: {e}")
            return ""

    def cleanup_temp_files(self):
        """Clean up temporary files"""
        try:
            if os.path.exists(self.temp_dir):
                for filename in os.listdir(self.temp_dir):
                    file_path = os.path.join(self.temp_dir, filename)
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                        logger.debug(f"Cleaned up temp file: {filename}")
        except Exception as e:
            logger.error(f"Error cleaning up temp files: {e}")

    def get_video_info(self, video_path: str) -> Dict:
        """Get video information using ffprobe"""
        try:
            cmd = [
                'ffprobe', '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-show_streams',
                video_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                return json.loads(result.stdout)
            else:
                return {}
        except Exception as e:
            logger.error(f"Error getting video info: {e}")
            return {}
