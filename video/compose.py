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
        os.makedirs(self.temp_dir, exist_ok=True)
        logger.info(f"VideoComposer loaded from {__file__}")

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
        """Get default video styles"""
        return {
            "clean-bold": {
                "font_family": "Arial-Bold",
                "font_size": 84,
                "text_color": "#FFFFFF",
                "stroke_width": 3,
                "stroke_color": "#000000",
                "caption_position": "center-bottom",
                "safe_margin": 200,
                "hook_font_size": 96,
                "background_color": "#1a1a1a"
            },
            "creator-minimal": {
                "font_family": "Arial",
                "font_size": 72,
                "text_color": "#FFFFFF",
                "stroke_width": 2,
                "stroke_color": "#333333",
                "caption_position": "center-bottom",
                "safe_margin": 180,
                "hook_font_size": 88,
                "background_color": "#2d2d2d"
            }
        }

    async def compose_video(
        self,
        voiceover: Voiceover,
        assets: AssetBundle,
        render_spec: RenderSpec,
        output_dir: str = "./data/renders"
    ) -> Optional[RenderResult]:
        """Compose final video with all elements (no captions)"""
        try:
            os.makedirs(output_dir, exist_ok=True)
            output_filename = f"video_{uuid.uuid4().hex}.mp4"
            output_path = os.path.join(output_dir, output_filename)
            style = self.styles.get(render_spec.style, self.styles["clean-bold"])

            success = await self._compose_with_ffmpeg(
                voiceover, assets, render_spec, style, output_path
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
                logger.info(f"Video composed successfully: {output_path} ({file_size_mb:.1f}MB)")
                return result
            return None
        except Exception as e:
            logger.error(f"Error composing video: {e}")
            return None

    async def _compose_with_ffmpeg(
        self,
        voiceover: Voiceover,
        assets: AssetBundle,
        render_spec: RenderSpec,
        style: Dict,
        output_path: str
    ) -> bool:
        """Compose video using FFmpeg (no captions)"""
        try:
            logger.info("VideoComposer::_compose_with_ffmpeg (no-captions build)")

            cmd = ['ffmpeg', '-y']  # overwrite
            filter_complex_parts: List[str] = []

            # 0) Inputs
            # Audio input 0 (voiceover)
            cmd.extend(['-i', voiceover.path])

            # Optional music
            music_input_index = 1
            if assets.music_path and os.path.exists(assets.music_path):
                cmd.extend(['-i', assets.music_path])
                music_exists = True
            else:
                music_exists = False

            # Video inputs start after audio/music
            video_inputs: List[int] = []
            next_index = 1 + (1 if music_exists else 0)
            for i, clip_path in enumerate(assets.video_clips[:5]):
                if os.path.exists(clip_path):
                    cmd.extend(['-i', clip_path])
                    video_inputs.append(next_index)
                    next_index += 1

            # 1) Video graph -> [video]
            if video_inputs:
                filter_complex_parts.append(
                    self._create_video_filter_complex(
                        video_inputs, render_spec, style, voiceover.duration_sec
                    )
                )
                video_output_label = "[video]"
            else:
                # Solid background if no clips
                filter_complex_parts.append(
                    f"color=c={style['background_color']}:s={render_spec.width}x{render_spec.height}:d={voiceover.duration_sec}[video]"
                )
                video_output_label = "[video]"

            # 2) Audio graph -> [audio]
            if music_exists:
                # Mix voiceover (0:a) with music
                filter_complex_parts.append(
                    f"[0:a][{music_input_index}:a]amix=inputs=2:duration=first:dropout_transition=2,volume=0.8[audio]"
                )
            else:
                # Pass-through voiceover via anull to create [audio]
                filter_complex_parts.append("[0:a]anull[audio]")

            audio_output_label = "[audio]"

            # Assemble filter_complex
            if filter_complex_parts:
                fc = ';'.join(filter_complex_parts)
                cmd.extend(['-filter_complex', fc])
                logger.debug("FILTER_COMPLEX:\n" + fc)

            # Map outputs (labels)
            cmd.extend(['-map', video_output_label])   # "[video]"
            cmd.extend(['-map', audio_output_label])   # "[audio]"
            logger.debug(f"MAPS: video={video_output_label}, audio={audio_output_label}")

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

            logger.debug("FFMPEG CMD:\n" + " ".join(cmd))
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                logger.info("FFmpeg composition completed successfully")
                return True
            else:
                logger.error(f"FFmpeg error: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"Error in FFmpeg composition: {e}")
            return False

    def _create_video_filter_complex(
        self, 
        video_inputs: List[int], 
        render_spec: RenderSpec, 
        style: Dict, 
        duration: float
    ) -> str:
        """
        Build a clean, ordered filtergraph:
          1) scale+crop each input -> [s{i}]
          2) trim each to equal duration -> [t{i}]
          3) concat once -> [video]
        If only one clip, just setpts -> [video].
        """
        W, H = render_spec.width, render_spec.height
        parts: List[str] = []

        # 1) Scale/crop to 9:16 -> [s{i}]
        for i, idx in enumerate(video_inputs):
            parts.append(
                f"[{idx}:v]"
                f"scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H}"
                f"[s{i}]"
            )

        if len(video_inputs) > 1:
            # 2) Trim each to equal share -> [t{i}]
            clip_dur = max(0.1, float(duration) / len(video_inputs))
            for i in range(len(video_inputs)):
                parts.append(f"[s{i}]trim=0:{clip_dur},setpts=PTS-STARTPTS[t{i}]")
            # 3) Concat once -> [video]
            concat_inputs = "".join(f"[t{i}]" for i in range(len(video_inputs)))
            parts.append(f"{concat_inputs}concat=n={len(video_inputs)}:v=1:a=0[video]")
        else:
            # Single clip: no concat, just normalize timestamps
            parts.append("[s0]setpts=PTS-STARTPTS[video]")

        return ";".join(parts)

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

    def create_hook_overlay(self, hook_text: str, duration: float = 2.0) -> str:
        """Create a temporary video file with hook overlay"""
        try:
            overlay_filename = f"hook_overlay_{uuid.uuid4().hex}.mp4"
            overlay_path = os.path.join(self.temp_dir, overlay_filename)
            cmd = [
                'ffmpeg', '-y',
                '-f', 'lavfi',
                '-i', f'color=c=black@0.3:s=1080x1920:d={duration}',
                '-vf', f'drawtext=text="{hook_text}":fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:fontsize=96:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2:enable=between(t,0,{duration})',
                '-c:v', 'libx264',
                '-pix_fmt', 'yuv420p',
                overlay_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                return overlay_path
            else:
                logger.error(f"Error creating hook overlay: {result.stderr}")
                return ""
        except Exception as e:
            logger.error(f"Error creating hook overlay: {e}")
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
