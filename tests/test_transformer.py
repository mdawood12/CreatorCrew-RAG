"""Tests for the Link Transformer's structured-beats contract.

Offline: every seam is monkeypatched — extract_source returns a fixed
source text, retrieval returns nothing, and the LLM is a stub that
serves prepared responses through a fake failover wrapper that counts
calls. Covers the beats upgrade: the model must return scene beats
(narration + generation-ready visual_prompt + on-screen text) plus a
CTA; narration is joined into original_script and measured with the
word 8-gram overlap gate — an over-limit package gets exactly one
full-structure rewrite attempt, a still-close package is returned
flagged needs_review, a malformed retry never crashes the run, and a
response with no usable beats is a hard error that saves nothing.

Run:  .venv/bin/python -m pytest tests/test_transformer.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import transformer             # noqa: E402

URL = "https://www.youtube.com/watch?v=abc123XYZ"

# 24 words — plenty of word 8-grams for the overlap check to bite on.
SOURCE = ("the quick brown fox jumps over the lazy dog near the river "
          "bank every single morning before the sun rises over the "
          "quiet hills")

# One beat whose narration is the source verbatim → ~100% overlap.
COPY_BEATS = [{
    "start_sec": 0,
    "narration": SOURCE,
    "visual_prompt": ("A red fox in a misty forest clearing at dawn, "
                      "wide tracking shot, golden light, nature "
                      "documentary style"),
    "on_screen_text": "Copied hook",
}]

# Two beats whose narrations share no 8-word run with SOURCE → ~0%.
FRESH_BEATS = [
    {
        "start_sec": 0,
        "narration": ("Cooking rice at home takes patience, a tight "
                      "lid, and exactly the right amount of water."),
        "visual_prompt": ("Close-up of hands rinsing white rice in a "
                          "steel bowl under a kitchen tap, soft morning "
                          "window light, slow push-in camera, "
                          "photorealistic cooking-show style"),
        "on_screen_text": "Perfect rice, every time",
    },
    {
        "start_sec": 5,
        "narration": ("Let the pot rest off the heat so the grains "
                      "finish steaming and turn fluffy."),
        "visual_prompt": ("Steam rising as a pot lid lifts in a cozy "
                          "kitchen, warm golden lighting, gentle "
                          "handheld camera, shallow depth of field"),
        "on_screen_text": "",
    },
]


def _beats_response(beats, cta="Follow for more ideas like this."):
    return json.dumps({
        "source_ideas": ["idea one", "idea two"],
        "angle": "a fresh angle",
        "cta": cta,
        "beats": beats,
    })


def _joined(beats) -> str:
    return " ".join(b["narration"] for b in beats)


class _FakeResponse:
    def __init__(self, content: str):
        self.content = content


class _FakeLLM:
    """Serves the prepared responses in order, one per invoke()."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)

    def invoke(self, prompt):
        assert self._responses, "LLM called more times than expected"
        return _FakeResponse(self._responses.pop(0))


@pytest.fixture()
def rig(monkeypatch):
    """Patch every transformer seam; return the shared counters."""
    state = {"llm_calls": 0, "saves": []}
    monkeypatch.setattr(transformer, "extract_source",
                        lambda url: (SOURCE, "video"))
    monkeypatch.setattr(transformer.tools, "retrieve",
                        lambda *a, **k: [])
    monkeypatch.setattr(transformer.tools, "format_context",
                        lambda chunks: ("", []))
    monkeypatch.setattr(transformer.memory, "save_output",
                        lambda *a, **k: state["saves"].append(a))
    monkeypatch.setattr(transformer.config, "get_llm", lambda: object())

    def install(responses: list[str]):
        fake_llm = _FakeLLM(responses)

        def _failover(make_call, attempts=3):
            state["llm_calls"] += 1
            return make_call(fake_llm)

        monkeypatch.setattr(transformer.config, "call_llm_with_failover",
                            _failover)

    state["install"] = install
    return state


def test_rewrite_rescues_copied_beats(rig):
    rig["install"]([_beats_response(COPY_BEATS),
                    _beats_response(FRESH_BEATS)])
    res = transformer.transform_link(URL)
    assert rig["llm_calls"] == 2
    assert res.overlap_pct <= 25.0
    assert res.needs_review is False
    assert len(res.beats) == 2
    assert res.beats[0].visual_prompt == FRESH_BEATS[0]["visual_prompt"]
    assert res.beats[1].visual_prompt == FRESH_BEATS[1]["visual_prompt"]
    assert res.original_script == _joined(FRESH_BEATS)
    assert len(rig["saves"]) == 1


def test_still_copied_after_rewrite_is_flagged(rig):
    rig["install"]([_beats_response(COPY_BEATS),
                    _beats_response(COPY_BEATS)])
    res = transformer.transform_link(URL)
    assert rig["llm_calls"] == 2
    assert res.overlap_pct > 25.0
    assert res.needs_review is True
    assert len(rig["saves"]) == 1


def test_missing_beats_is_a_hard_error(rig):
    rig["install"]([json.dumps({
        "source_ideas": ["idea one"],
        "angle": "a fresh angle",
        "cta": "Follow for more.",
    })])
    with pytest.raises(RuntimeError):
        transformer.transform_link(URL)
    assert rig["saves"] == []


def test_blank_narration_beats_are_unusable(rig):
    rig["install"]([_beats_response([{
        "start_sec": 0,
        "narration": "   ",
        "visual_prompt": "A scene with no narration",
        "on_screen_text": "",
    }])])
    with pytest.raises(RuntimeError):
        transformer.transform_link(URL)
    assert rig["saves"] == []


def test_clean_first_response_parses_beats_and_cta(rig):
    rig["install"]([_beats_response(
        FRESH_BEATS, cta="Subscribe for weekly kitchen wins.")])
    res = transformer.transform_link(URL)
    assert rig["llm_calls"] == 1
    assert res.needs_review is False
    assert res.original_script == _joined(FRESH_BEATS)
    assert res.cta == "Subscribe for weekly kitchen wins."
    assert len(res.beats) == 2
    first, second = res.beats
    assert first.start_sec == 0.0
    assert first.visual_prompt == FRESH_BEATS[0]["visual_prompt"]
    assert first.on_screen_text == "Perfect rice, every time"
    assert second.start_sec == 5.0
    assert second.on_screen_text == ""
    assert len(rig["saves"]) == 1


def test_malformed_retry_keeps_first_result(rig):
    rig["install"]([_beats_response(COPY_BEATS),
                    "Sorry, I cannot help with that."])
    res = transformer.transform_link(URL)
    assert rig["llm_calls"] == 2
    assert res.overlap_pct > 25.0
    assert res.needs_review is True
    assert len(res.beats) == 1
    assert res.beats[0].narration == SOURCE
    assert len(rig["saves"]) == 1
