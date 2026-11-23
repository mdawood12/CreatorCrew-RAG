"""presets.py — the five editing presets as plain data (not code).

A preset is {op_id: {"enabled": bool, "params": {key: value}}} merged
over the registry defaults. "Minimal" reproduces the ORIGINAL splitter
behaviour exactly (blur-pad 9:16, the classic grade, hook + progress
bar, loudnorm -14) so nothing changes for existing users until they
choose a different preset.
"""
from __future__ import annotations

from . import registry

PRESETS: dict[str, dict] = {
    "Minimal": {
        "reframe": {"enabled": True, "params": {"ratio": "9:16", "mode": "blur"}},
        "grade": {"enabled": True, "params": {}},
        "hook": {"enabled": True, "params": {}},
        "loudnorm": {"enabled": True, "params": {}},
    },
    "Professional": {
        "reframe": {"enabled": True, "params": {"ratio": "9:16", "mode": "blur"}},
        "grade": {"enabled": True, "params": {"sharpen": 0.4}},
        "hook": {"enabled": True, "params": {}},
        "captions": {"enabled": True, "params": {}},
        "voice_clarity": {"enabled": True, "params": {}},
        "loudnorm": {"enabled": True, "params": {}},
    },
    "Cinematic": {
        "reframe": {"enabled": True, "params": {"ratio": "16:9", "mode": "crop"}},
        "zoom": {"enabled": True, "params": {"amount": 0.15}},
        "grade": {"enabled": True, "params": {
            "contrast": 1.12, "saturation": 1.05, "brightness": 0.0,
            "gamma": 0.97, "sharpen": 0.3}},
        "transitions": {"enabled": True, "params": {}},
        "voice_clarity": {"enabled": True, "params": {}},
        "loudnorm": {"enabled": True, "params": {}},
    },
    "Social Media": {
        "silence_trim": {"enabled": True, "params": {}},
        "reframe": {"enabled": True, "params": {"ratio": "9:16", "mode": "crop"}},
        "zoom": {"enabled": True, "params": {"amount": 0.10}},
        "grade": {"enabled": True, "params": {
            "contrast": 1.08, "saturation": 1.25, "brightness": 0.02,
            "sharpen": 0.8}},
        "hook": {"enabled": True, "params": {}},
        "captions": {"enabled": True, "params": {"font_size": 58}},
        "transitions": {"enabled": True, "params": {"every_sec": 5.0}},
        "loudnorm": {"enabled": True, "params": {}},
    },
    "Custom": {},   # starts from registry defaults, everything off
}

PRESET_NAMES = list(PRESETS)


def build_config(preset: str) -> dict:
    """Full config for a preset: registry defaults overlaid with the
    preset's choices. Returns {op_id: {"enabled", "params"}}."""
    registry.load_operations()
    cfg = registry.default_config()
    for op_id, choice in PRESETS.get(preset, {}).items():
        if op_id not in cfg:
            continue
        cfg[op_id]["enabled"] = bool(choice.get("enabled", False))
        cfg[op_id]["params"].update(choice.get("params", {}))
    return cfg
