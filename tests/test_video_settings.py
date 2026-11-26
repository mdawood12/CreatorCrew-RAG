"""Tests for video_settings.py pure functions (no Streamlit needed).

Covers fmt(), auto_scene_count(), compute() pacing warnings and the
Section 8 contract of Master Prompt v2: target_duration_seconds is
15..300 and a multiple of 5; scene_count is 1..120; ~5s per scene;
~150 voiceover words per minute.

Run:  .venv/bin/python -m pytest tests/test_video_settings.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import video_settings as vs


def test_fmt():
    assert vs.fmt(45) == "0:45"
    assert vs.fmt(60) == "1:00"
    assert vs.fmt(90) == "1:30"
    assert vs.fmt(300) == "5:00"


def test_auto_scene_count_default_pacing():
    # ~5 seconds per scene, rounded up, never below 1.
    assert vs.auto_scene_count(45) == 9
    assert vs.auto_scene_count(60) == 12
    assert vs.auto_scene_count(300) == 60
    assert vs.auto_scene_count(15) == 3


def test_compute_happy_path_no_warnings():
    r = vs.compute(60, 12)
    assert r["duration_seconds"] == 60
    assert r["duration_label"] == "1:00"
    assert r["scene_count"] == 12
    assert r["avg_scene_seconds"] == 5.0
    assert r["voiceover_words"] == 150
    assert r["warnings"] == []


def test_compute_long_scenes_warn():
    r = vs.compute(300, 6)  # 50s per scene
    assert r["avg_scene_seconds"] == 50.0
    assert len(r["warnings"]) == 1
    assert "Add scenes" in r["warnings"][0]


def test_compute_fast_cuts_warn():
    r = vs.compute(45, 60)  # 0.75s per scene
    assert r["avg_scene_seconds"] == 0.8
    assert len(r["warnings"]) == 1
    assert "Reduce scenes" in r["warnings"][0]


def test_compute_voiceover_words_scale():
    assert vs.compute(120, 24)["voiceover_words"] == 300
    assert vs.compute(30, 6)["voiceover_words"] == 75


def test_contract_ranges():
    # Section 8: durations 15..300 in steps of 5; scenes 1..120.
    assert all(15 <= s <= 300 and s % 5 == 0 for s in vs.DURATION_PRESETS)
    assert vs.CUSTOM_DURATION_RANGE == (15, 300, 5)
    assert all(1 <= n <= 120 for n in vs.SCENE_PRESETS)
    assert vs.CUSTOM_SCENE_RANGE == (1, 120)


def test_clip_label():
    assert vs.clip_label(10) == "10 seconds"
    assert vs.clip_label(45) == "45 seconds"
    assert vs.clip_label(60) == "1 minute"
    assert vs.clip_label(90) == "1 minute 30 seconds"
    assert vs.clip_label(120) == "2 minutes"


def test_clip_presets_contract():
    # Step 3 clip settings: 45s and 1-minute options must exist,
    # durations sorted, clip counts inside the custom range 1..20.
    assert 45 in vs.CLIP_DURATION_PRESETS
    assert 60 in vs.CLIP_DURATION_PRESETS
    assert vs.CLIP_DURATION_PRESETS == sorted(vs.CLIP_DURATION_PRESETS)
    assert all(1 <= n <= 20 for n in vs.CLIP_COUNT_PRESETS)
    assert vs.CUSTOM_CLIP_DURATION_RANGE == (5, 300, 5)
    assert vs.CUSTOM_CLIP_COUNT_RANGE == (1, 20)
