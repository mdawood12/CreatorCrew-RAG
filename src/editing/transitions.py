"""transitions.py — crossfade (xfade) transitions inside a clip.

The clip is split into sub-segments (at most 4) and rejoined with
short crossfades (video xfade + audio acrossfade), giving the smooth
dynamic cuts used in short-form editing. Very short clips pass through.
"""
from __future__ import annotations

from pathlib import Path

from . import registry
from ._util import probe, run_ffmpeg

MAX_PARTS = 4


def transitions(in_path: Path, params: dict, ctx: dict) -> Path:
    info = probe(in_path)
    dur = info["duration"]
    every = float(params["every_sec"])
    fade = float(params["fade_sec"])
    n = int(dur // every)
    if n < 2 or dur < every * 1.6:
        return in_path
    n = min(n, MAX_PARTS)
    seg = dur / n
    has_audio = info["has_audio"]

    v_parts, a_parts = [], []
    for i in range(n):
        s, e = i * seg, (dur if i == n - 1 else (i + 1) * seg)
        v_parts.append(f"[0:v]trim=start={s:.3f}:end={e:.3f},"
                       f"setpts=PTS-STARTPTS,fps=30,format=yuv420p[v{i}]")
        if has_audio:
            a_parts.append(f"[0:a]atrim=start={s:.3f}:end={e:.3f},"
                           f"asetpts=PTS-STARTPTS[a{i}]")
    graph = ";".join(v_parts + a_parts)
    # Chain the video crossfades; offsets shrink by one fade per join.
    cur = "v0"
    for i in range(1, n):
        offset = i * seg - i * fade
        graph += (f";[{cur}][v{i}]xfade=transition=fade:"
                  f"duration={fade:.3f}:offset={offset:.3f}[x{i}]")
        cur = f"x{i}"
    graph += f";[{cur}]null[outv]"
    if has_audio:
        acur = "a0"
        for i in range(1, n):
            graph += f";[{acur}][a{i}]acrossfade=d={fade:.3f}[af{i}]"
            acur = f"af{i}"
        graph += f";[{acur}]anull[outa]"
        maps = ["-map", "[outv]", "-map", "[outa]"]
    else:
        maps = ["-map", "[outv]"]
    out = ctx["workdir"] / f"{in_path.stem}_xfade.mp4"
    run_ffmpeg(["-i", str(in_path), "-filter_complex", graph, *maps,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "aac", "-b:a", "160k", str(out)])
    return out


registry.register(registry.Operation(
    id="transitions", stage="trim", phase="B", label="Dynamic transitions",
    help="Splits the clip into beats and joins them with smooth crossfades.",
    func=transitions,
    params=[
        {"key": "every_sec", "type": "float", "default": 6.0, "min": 3.0,
         "max": 15.0, "step": 1.0, "label": "Beat length (seconds)",
         "help": "A transition roughly every this many seconds."},
        {"key": "fade_sec", "type": "float", "default": 0.4, "min": 0.1,
         "max": 1.0, "step": 0.1, "label": "Fade length (seconds)",
         "help": "How long each crossfade lasts."},
    ]))
