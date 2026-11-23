#!/usr/bin/env python
"""
benchmark.py — timing harness for the Real-World Verification Stage.

Times, on ONE machine and ONE video:
  * faster-whisper transcription with the `tiny` model
  * faster-whisper transcription with the `base` model
    (both via the app's own src/tools.py + src/config.py path, so the
    numbers reflect the app, not a re-implementation; model load time
    is included and noted)
  * one standard render (the splitter's Minimal-preset render via
    src/splitter.render_clip) of the first --clip-seconds of video

Prints a markdown table to stdout. It writes NOTHING into
REAL-WORLD-VERIFICATION.md — copy numbers there manually, only for
runs on real authorized samples.

Usage:
    .venv/bin/python scripts/benchmark.py <video> [--clip-seconds 15]

The timings are only meaningful for the machine and video named in
the output header. A run on the synthetic test video proves the
harness works; it is NOT a performance claim.
"""
from __future__ import annotations

import argparse
import platform
import resource
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, tools          # noqa: E402
from src.editing._util import probe    # noqa: E402


def _timed(fn) -> tuple[float, object, str | None]:
    t0 = time.perf_counter()
    try:
        result = fn()
        return time.perf_counter() - t0, result, None
    except Exception as e:  # harness must report, never crash mid-table
        return time.perf_counter() - t0, None, f"{type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("video", help="Path to the video file to time.")
    ap.add_argument("--clip-seconds", type=float, default=15.0,
                    help="Length of the standard render (default 15).")
    args = ap.parse_args()

    video = Path(args.video)
    if not video.exists():
        print(f"error: file not found: {video}", file=sys.stderr)
        return 2
    info = probe(video)
    clip_len = min(args.clip_seconds, info["duration"] or args.clip_seconds)

    print(f"## Benchmark run — {video.name}")
    print()
    print(f"- Machine: {platform.platform()} · "
          f"Python {platform.python_version()}")
    print(f"- Video: {info['duration']:.1f}s · "
          f"{info['width']}x{info['height']} · "
          f"audio: {'yes' if info['has_audio'] else 'no'}")
    print(f"- App whisper default (config.WHISPER_MODEL): "
          f"{config.WHISPER_MODEL}")
    print()
    print("| Stage | Model / preset | Time (s) | Result |")
    print("|-------|----------------|----------|--------|")

    total = 0.0
    for model in ("tiny", "base"):
        dt, segs, err = _timed(
            lambda m=model: tools.transcript_via_whisper(
                str(video), model_name=m))
        total += dt
        if err:
            result = f"FAILED — {err}"
        elif not segs:
            result = "no transcript produced"
        else:
            result = (f"{len(segs)} segments · word timings: "
                      f"{tools.word_timings_label(segs)}")
        print(f"| Transcribe (incl. model load) | {model} | "
              f"{dt:.1f} | {result} |")

    from src.schemas import ClipCandidate
    from src.splitter import render_clip
    out_dir = config.BASE_DIR / ".tmp" / "benchmark"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "benchmark-clip.mp4"
    clip = ClipCandidate(start_sec=0.0, end_sec=clip_len,
                         hook="benchmark", reason="benchmark harness")
    dt, _res, err = _timed(lambda: render_clip(video, clip, out_path))
    total += dt
    if err:
        result = f"FAILED — {err}"
    else:
        rinfo = probe(out_path)
        result = (f"{rinfo['width']}x{rinfo['height']} · "
                  f"{rinfo['duration']:.1f}s · {out_path.name}")
    print(f"| Render (Minimal preset, first {clip_len:.0f}s) | — | "
          f"{dt:.1f} | {result} |")

    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(f"| **Total (all stages)** | | **{total:.1f}** | |")
    print()
    print(f"Process peak RSS: {peak_mb:.0f} MB (this harness process, "
          f"includes both whisper models loaded in sequence).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
