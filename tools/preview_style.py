# tools/preview_style.py
import argparse
import os
import sys
import subprocess
import uuid
from pathlib import Path
from typing import Optional, List
import asyncio

# --- make imports work when running as a script or module ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from models.schemas import AssetBundle, RenderSpec, Voiceover  # type: ignore
from video.compose import VideoComposer  # type: ignore

OUT_DIR = Path("./data/renders")
VOICE_DIR = Path("./data/voice")
STOCK_DIR = Path("./data/assets/stock")
CHAR_DIR = Path("./data/assets/characters")


def ensure_dirs():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    STOCK_DIR.mkdir(parents=True, exist_ok=True)
    CHAR_DIR.mkdir(parents=True, exist_ok=True)


def make_silent_audio(seconds: float) -> str:
    """Create a short silent audio file for preview (MP3 is fine for FFmpeg)."""
    ensure_dirs()
    out = VOICE_DIR / f"preview_silence_{uuid.uuid4().hex}.mp3"
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=48000:cl=mono",
        "-t",
        str(seconds),
        "-c:a",
        "libmp3lame",
        "-b:a",
        "128k",
        str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return str(out)


def pick_any_stock() -> Optional[str]:
    """Pick any stock clip if present (optional)."""
    if STOCK_DIR.exists():
        for f in STOCK_DIR.iterdir():
            if f.suffix.lower() in {".mp4", ".mov", ".mkv"}:
                return str(f)
    return None


def build_asset_bundle(stock_path: Optional[str]) -> AssetBundle:
    """Minimal bundle (music/captions optional)."""
    return AssetBundle(
        video_clips=[stock_path] if stock_path else [],
        music_path=None,
        srt_path=None,
    )


async def render_preview_video(style_name: str, seconds: float, width: int, height: int, fps: int) -> Optional[str]:
    """Render a short preview video using the selected style; return path or None."""
    # 1) Silent audio
    audio_path = make_silent_audio(seconds)
    voiceover = Voiceover(
        path=audio_path,
        duration_sec=float(seconds),
        provider="preview",
        voice_id="preview",  # <-- REQUIRED by your Pydantic model
    )

    # 2) Assets
    stock = pick_any_stock()
    assets = build_asset_bundle(stock)

    # 3) Render spec
    spec = RenderSpec(width=width, height=height, fps=fps, style=style_name)

    # 4) Compose
    composer = VideoComposer()
    # Create a minimal script_package-like object so the title will render
    class _Pkg:
        pass

    pkg = _Pkg()
    pkg.title = f"Style Preview: {style_name}"

    result = await composer.compose_video(
        voiceover=voiceover,
        assets=assets,
        render_spec=spec,
        script_package=pkg,
        output_dir=str(OUT_DIR),
    )
    return result.path if result else None


async def render_single_frame(style_name: str, width: int, height: int, fps: int) -> str:
    """
    Render a single PNG frame by making a 1s video then extracting frame 0.
    Quicker when you’re just checking colors/layout.
    """
    vid = await render_preview_video(style_name, seconds=1.0, width=width, height=height, fps=fps)
    if not vid:
        raise RuntimeError("Preview video failed; cannot extract frame.")
    png_out = OUT_DIR / f"style_preview_{style_name}_{uuid.uuid4().hex}.png"
    cmd = ["ffmpeg", "-y", "-i", vid, "-vframes", "1", str(png_out)]
    subprocess.run(cmd, check=True, capture_output=True)
    return str(png_out)


def main():
    ap = argparse.ArgumentParser(description="Quick style preview without running the full pipeline.")
    ap.add_argument("--style", default="clean-bold", help="Style key from ./config/styles.json")
    ap.add_argument("--seconds", type=float, default=5.0, help="Preview duration (ignored if --frame-only=1)")
    ap.add_argument("--width", type=int, default=1080)
    ap.add_argument("--height", type=int, default=1920)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--frame-only", type=int, default=0, help="1 to render a single PNG frame instead of a video")
    args = ap.parse_args()

    ensure_dirs()

    if args.frame_only == 1:
        png = asyncio.run(render_single_frame(args.style, args.width, args.height, args.fps))
        print(f"✅ Single-frame preview saved to: {png}")
    else:
        vid = asyncio.run(render_preview_video(args.style, args.seconds, args.width, args.height, args.fps))
        if vid:
            print(f"✅ Video preview saved to: {vid}")
        else:
            print("❌ Failed to render preview.")


if __name__ == "__main__":
    main()
