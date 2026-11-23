"""_util.py — shared FFmpeg/ffprobe helpers for the editing package."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FFMPEG_TIMEOUT = 1800


def run_ffmpeg(args: list[str], timeout: int = FFMPEG_TIMEOUT) -> None:
    """Run ffmpeg with the given argument list (without the binary name).
    Raises RuntimeError with the tail of stderr on failure."""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError("FFmpeg failed: " + (r.stderr or "")[-600:])


def probe(path: str | Path) -> dict:
    """ffprobe a media file. Returns a normalised dict:
    {duration, size, width, height, fps, video_codec, audio_codec,
     has_audio, format}. Raises ValueError if the file is unreadable
    or has no video stream."""
    p = Path(path)
    if not p.exists():
        raise ValueError(f"File not found: {p}")
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(p)],
        capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise ValueError(f"Could not read media file: {p.name}")
    try:
        data = json.loads(r.stdout)
    except Exception:
        raise ValueError(f"Could not read media file: {p.name}")
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ValueError(f"No video stream found in: {p.name}")
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = data.get("format", {})
    fps = 0.0
    rate = video.get("avg_frame_rate") or "0/1"
    try:
        num, den = rate.split("/")
        fps = float(num) / float(den) if float(den) else 0.0
    except Exception:
        fps = 0.0
    return {
        "duration": float(fmt.get("duration") or video.get("duration") or 0),
        "size": int(fmt.get("size") or p.stat().st_size),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": fps,
        "video_codec": video.get("codec_name", ""),
        "audio_codec": (audio or {}).get("codec_name", ""),
        "has_audio": audio is not None,
        "format": (fmt.get("format_name") or "").split(",")[0],
    }


def esc_text(text: str) -> str:
    """Escape a string for use inside an FFmpeg drawtext filter."""
    return (text.replace("\\", "\\\\").replace(":", "\\:")
            .replace("'", "\u2019").replace("%", "\\%"))


def wrap_lines(text: str, width: int = 30, max_lines: int = 2) -> list[str]:
    """Word-wrap text to at most `max_lines` lines of ~`width` chars."""
    words, lines = text.split(), []
    for w in words:
        if lines and len(lines[-1]) + len(w) + 1 <= width:
            lines[-1] += " " + w
        elif len(lines) < max_lines:
            lines.append(w)
        else:
            lines[-1] = lines[-1].rstrip("…") + "…"
            break
    return lines
