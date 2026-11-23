"""trim.py — silence trimming via FFmpeg silencedetect.

Detects silent stretches, keeps the non-silent ranges (with a small
padding so speech is never clipped) and rejoins them with trim/concat.
If no silence is found the clip passes through unchanged.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from . import registry
from ._util import probe, run_ffmpeg


def _detect_silences(path: Path, noise_db: float, min_dur: float) -> list[tuple[float, float]]:
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path),
         "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-"],
        capture_output=True, text=True, timeout=600)
    starts = [float(x) for x in re.findall(r"silence_start:\s*([\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([\d.]+)", r.stderr)]
    return list(zip(starts, ends))


def silence_trim(in_path: Path, params: dict, ctx: dict) -> Path:
    info = probe(in_path)
    dur = info["duration"]
    if not info["has_audio"] or dur <= 0:
        return in_path
    silences = _detect_silences(in_path, params["noise_db"], params["min_silence"])
    if not silences:
        return in_path
    pad = float(params["padding"])
    keep: list[tuple[float, float]] = []
    cursor = 0.0
    for s, e in silences:
        seg = (cursor, max(cursor, s + pad))
        if seg[1] - seg[0] >= 0.25:
            keep.append(seg)
        cursor = min(dur, max(cursor, e - pad))
    tail = (cursor, dur)
    if tail[1] - tail[0] >= 0.25:
        keep.append(tail)
    if not keep or len(keep) == 1 and keep[0] == (0.0, dur):
        return in_path
    parts, labels = [], []
    for i, (s, e) in enumerate(keep):
        parts.append(f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS[v{i}]")
        parts.append(f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[a{i}]")
        labels.append(f"[v{i}][a{i}]")
    graph = ";".join(parts) + ";" + "".join(labels) + \
        f"concat=n={len(keep)}:v=1:a=1[outv][outa]"
    out = ctx["workdir"] / f"{in_path.stem}_notsilence.mp4"
    run_ffmpeg(["-i", str(in_path), "-filter_complex", graph,
                "-map", "[outv]", "-map", "[outa]",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "aac", "-b:a", "160k", str(out)])
    return out


registry.register(registry.Operation(
    id="silence_trim", stage="trim", phase="A",
    label="Silence trimming",
    help="Cuts silent pauses out of the clip so the pacing stays tight.",
    func=silence_trim,
    params=[
        {"key": "noise_db", "type": "float", "default": -35.0, "min": -60.0,
         "max": -15.0, "step": 1.0, "label": "Silence threshold (dB)",
         "help": "Audio quieter than this counts as silence."},
        {"key": "min_silence", "type": "float", "default": 0.6, "min": 0.2,
         "max": 3.0, "step": 0.1, "label": "Minimum silence (seconds)",
         "help": "Pauses shorter than this are kept."},
        {"key": "padding", "type": "float", "default": 0.08, "min": 0.0,
         "max": 0.4, "step": 0.02, "label": "Edge padding (seconds)",
         "help": "Breathing room kept around speech so words never clip."},
    ]))
