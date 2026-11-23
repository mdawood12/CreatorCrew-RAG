"""pipeline.py — the editing pipeline runner.

Extracts the requested segment once, then applies the enabled
operations in the ONE fixed stage order (registry.STAGE_ORDER).
Isolation rule: every op writes its own temp file; if an op fails it is
skipped, the failure is recorded in the result's "warnings" list, and
the render continues with the last good file. A render therefore only
fails outright when the segment extraction itself fails.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from ..config import logger
from . import registry
from ._util import run_ffmpeg


def extract_segment(source: Path, start: float, end: float,
                    workdir: Path) -> Path:
    """Cut [start, end] out of the source into a work file (re-encoded
    so every downstream filter starts from clean keyframes)."""
    dur = max(end - start, 0.5)
    out = workdir / "segment.mp4"
    run_ffmpeg(["-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(source),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-c:a", "aac", "-b:a", "192k", str(out)])
    return out


def render_segment(source: str | Path, start: float, end: float,
                   config: dict, out_path: str | Path,
                   workdir: str | Path,
                   extras: dict | None = None,
                   progress_cb: Callable[[str, int, int], None] | None = None
                   ) -> dict:
    """Render one clip through the editing pipeline.

    config: {op_id: {"enabled": bool, "params": {...}}} (see presets).
    extras: shared context for ops — hook_text, bgm_path, pip_path,
    logo_path. Returns {"file", "applied": [op_id...], "warnings": [...]}.
    """
    registry.load_operations()
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    current = extract_segment(Path(source), start, end, workdir)
    ctx = {"workdir": workdir, "extras": extras or {}}
    ops = [op for op in registry.ordered_ops()
           if config.get(op.id, {}).get("enabled")]
    applied, warnings = [], []
    for i, op in enumerate(ops):
        if progress_cb:
            progress_cb(op.id, i, len(ops))
        params = {**op.defaults(), **config[op.id].get("params", {})}
        try:
            result = op.func(current, params, ctx)
            if result != current:
                current = result
            applied.append(op.id)
        except Exception as e:                      # isolation: skip + warn
            msg = f"{op.label} skipped: {str(e)[:160]}"
            logger.warning("Pipeline: %s", msg)
            warnings.append(msg)
    if progress_cb:
        progress_cb("export", len(ops), len(ops))
    if current != out_path:
        if current.suffix.lower() == ".mp4":
            # Final tidy pass: faststart for instant web preview.
            try:
                run_ffmpeg(["-i", str(current), "-c", "copy",
                            "-movflags", "+faststart", str(out_path)])
            except Exception:
                shutil.copyfile(current, out_path)
        else:
            shutil.copyfile(current, out_path)
    return {"file": str(out_path), "applied": applied, "warnings": warnings}
