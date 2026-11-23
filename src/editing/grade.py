"""grade.py — editorial colour grade: contrast, saturation, brightness,
gamma and sharpening. The Minimal preset's values reproduce the original
splitter look exactly (eq 1.05 / 1.12 / 0.01 + unsharp 0.6).
"""
from __future__ import annotations

from pathlib import Path

from . import registry
from ._util import run_ffmpeg


def grade(in_path: Path, params: dict, ctx: dict) -> Path:
    vf = (f"eq=contrast={params['contrast']:.3f}"
          f":saturation={params['saturation']:.3f}"
          f":brightness={params['brightness']:.3f}"
          f":gamma={params['gamma']:.3f}")
    sharp = float(params.get("sharpen", 0.0))
    if sharp > 0:
        vf += f",unsharp=5:5:{sharp:.2f}"
    out = ctx["workdir"] / f"{in_path.stem}_grade.mp4"
    run_ffmpeg(["-i", str(in_path), "-vf", vf,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "aac", "-b:a", "160k", str(out)])
    return out


registry.register(registry.Operation(
    id="grade", stage="grade", phase="A", label="Colour grade",
    help="Adjusts the look of the picture — contrast, colour and brightness.",
    func=grade,
    params=[
        {"key": "contrast", "type": "float", "default": 1.05, "min": 0.5,
         "max": 1.8, "step": 0.01, "label": "Contrast", "help": "1.0 = unchanged."},
        {"key": "saturation", "type": "float", "default": 1.12, "min": 0.0,
         "max": 2.5, "step": 0.01, "label": "Saturation",
         "help": "Colour intensity. 1.0 = unchanged."},
        {"key": "brightness", "type": "float", "default": 0.01, "min": -0.4,
         "max": 0.4, "step": 0.01, "label": "Brightness",
         "help": "0 = unchanged; positive brightens."},
        {"key": "gamma", "type": "float", "default": 1.0, "min": 0.5,
         "max": 2.0, "step": 0.01, "label": "Gamma",
         "help": "Mid-tone brightness. 1.0 = unchanged."},
        {"key": "sharpen", "type": "float", "default": 0.6, "min": 0.0,
         "max": 2.0, "step": 0.1, "label": "Sharpen",
         "help": "Edge sharpening amount. 0 = off."},
    ]))
