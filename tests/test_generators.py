"""Tests for Master Prompt generation (Step 2 — src/generators.py).

Offline: the LLM is a stub served through a fake failover wrapper
that counts calls AND captures the prompts it receives, so the lock
rule is verified at the seam — the prompt handed to the model must
contain the template's locked character descriptions, visual style
and negative prompt verbatim. Storage tests run against a TEMP
database (config.DB_PATH monkeypatched), never the real one.

Covers: template generation from only a niche name (with clamping),
topic pack generation from a locked template, defensive beat
parsing, the markdown production pack, end-to-end auto-save onto a
topic, and malformed-JSON failures.

Run:  .venv/bin/python -m pytest tests/test_generators.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, generators, master_prompt, memory  # noqa: E402
from src.schemas import MasterPromptTemplate, TemplateCharacter  # noqa: E402

NICHE_RESPONSE = json.dumps({
    "name": "Deep Sea Wonders",
    "characters": [
        {"name": "Nixie",
         "description": "A small silver-blue lanternfish with a "
                        "glowing lure, the curious guide of the crew"},
        {"name": "Bram",
         "description": "A giant Greenland shark with scarred grey "
                        "skin, the wise elder of the deep"},
    ],
    "visual_style": "Cinematic photorealistic deep-ocean documentary, "
                    "bioluminescent accents, vertical 9:16",
    "target_format": "Reel 60s",
    "beat_count": 0,
    "hook_style": "Curiosity gap in the first 3 seconds",
    "cta": "LIKE • SHARE • FOLLOW",
    "language": "English",
    "tone": "Calm, knowledgeable guide",
    "caption_style": "Keyword-first, one Pick-ONE question",
    "hashtags": "#DeepSea #OceanFacts",
})

TEMPLATE = MasterPromptTemplate(
    name="Paws & Plates — Restaurant Cats",
    characters=[TemplateCharacter(
        name="Gus",
        description="fluffy orange tabby, green eyes, "
                    "restaurant manager")],
    visual_style="cozy American diner, warm cinematic light, "
                 "vertical 9:16",
    negative_prompt="no text, no watermark, no distorted paws",
    target_format="Reel 60s",
    beat_count=0,
    hook_style="bold question in the first 3 seconds",
    cta="LIKE • SHARE • FOLLOW",
    language="English",
    tone="friendly",
    caption_style="keyword-first",
    hashtags="#CatsOfFacebook")

PACK_BEATS = [
    {"start_sec": 0, "duration_sec": 5,
     "narration": "Can one cat flip a pancake bigger than his head?",
     "visual_prompt": "Gus, fluffy orange tabby, green eyes, "
                      "restaurant manager, in a cozy American diner, "
                      "warm cinematic light, vertical 9:16, staring "
                      "at a giant pancake on a griddle",
     "on_screen_text": "The giant pancake",
     "music_cue": "light playful music, low"},
    {"start_sec": 5, "duration_sec": 5,
     "narration": "Gus takes a breath, grips the spatula, and flips.",
     "visual_prompt": "Gus, fluffy orange tabby, green eyes, "
                      "restaurant manager, flipping a giant pancake "
                      "in a cozy American diner, warm cinematic light",
     "on_screen_text": "",
     "music_cue": ""},
]

PACK_RESPONSE = json.dumps({
    "title": "Gus and the Giant Pancake",
    "hook": "Can one cat flip a pancake bigger than his head?",
    "beats": PACK_BEATS,
    "cta": "LIKE • SHARE • FOLLOW",
    "caption": "Pancake day at Paws & Plates — would Gus make it "
               "as a line cook? Pick ONE: Yes / No",
    "hashtags": "#CatsOfFacebook",
    "total_duration_sec": 60,
})


class _FakeResponse:
    def __init__(self, content: str):
        self.content = content


class _FakeLLM:
    """Serves prepared responses in order; records every prompt."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.prompts: list[str] = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        assert self._responses, "LLM called more times than expected"
        return _FakeResponse(self._responses.pop(0))


@pytest.fixture()
def rig(monkeypatch):
    """Patch the generators LLM seams; return the shared state."""
    state = {"llm_calls": 0, "llm": None}
    monkeypatch.setattr(generators.config, "get_llm", lambda: object())

    def install(responses: list[str]):
        fake_llm = _FakeLLM(responses)
        state["llm"] = fake_llm

        def _failover(make_call, attempts=3):
            state["llm_calls"] += 1
            return make_call(fake_llm)

        monkeypatch.setattr(generators.config,
                            "call_llm_with_failover", _failover)

    state["install"] = install
    return state


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_generators.db"
    monkeypatch.setattr(config, "DB_PATH", db_file)
    memory.init_db()
    assert db_file.exists()
    return db_file


# ----------------------------------------------------------------------
# (a) Template from only a niche name
# ----------------------------------------------------------------------
def test_niche_generation_builds_full_template(rig):
    rig["install"]([NICHE_RESPONSE])
    tpl = generators.generate_template_from_niche("deep sea creatures")
    assert rig["llm_calls"] == 1
    assert isinstance(tpl, MasterPromptTemplate)
    assert tpl.name == "Deep Sea Wonders"
    assert [c.name for c in tpl.characters] == ["Nixie", "Bram"]
    assert "lanternfish" in tpl.characters[0].description
    assert tpl.target_format == "Reel 60s"
    assert tpl.language == "English"
    assert tpl.cta == "LIKE • SHARE • FOLLOW"
    # The premium standard itself drives the generation.
    assert "Senior Multimedia Specialist" in rig["llm"].prompts[0]
    assert "deep sea creatures" in rig["llm"].prompts[0]


def test_niche_generation_clamps_and_defaults(rig):
    rig["install"]([json.dumps({
        # no name at all, bogus format + language, string beat_count
        "characters": [{"name": "Solo", "description": "the host"}],
        "target_format": "Widescreen Epic",
        "language": "Klingon",
        "beat_count": "many",
    })])
    tpl = generators.generate_template_from_niche("home workouts")
    assert tpl.name == "home workouts"  # falls back to the niche
    assert tpl.target_format == "Reel 60s"
    assert tpl.language == "English"
    assert tpl.beat_count == 0
    assert tpl.characters[0].name == "Solo"
    # The schema default negative prompt still applies.
    assert "no watermark" in tpl.negative_prompt


# ----------------------------------------------------------------------
# (b) Topic pack — the lock rule verified at the seam
# ----------------------------------------------------------------------
def test_topic_pack_prompt_carries_the_locked_template(rig):
    rig["install"]([PACK_RESPONSE])
    pack = generators.generate_topic_pack(
        TEMPLATE, "Gus tries to cook a giant pancake")
    assert rig["llm_calls"] == 1
    prompt = rig["llm"].prompts[0]
    # Locked values reach the model verbatim — characters, style,
    # negative prompt, CTA — plus the hard rule itself.
    assert "fluffy orange tabby, green eyes, restaurant manager" in prompt
    assert "cozy American diner, warm cinematic light" in prompt
    assert "no text, no watermark, no distorted paws" in prompt
    assert "NEVER invent a new character" in prompt
    assert "Gus tries to cook a giant pancake" in prompt
    # And the returned pack parses into the production shape.
    assert pack["title"] == "Gus and the Giant Pancake"
    assert len(pack["beats"]) == 2
    assert pack["beats"][0]["narration"].startswith("Can one cat")
    assert pack["beats"][0]["music_cue"] == "light playful music, low"
    assert pack["cta"] == "LIKE • SHARE • FOLLOW"
    assert pack["total_duration_sec"] == 60


def test_topic_pack_fills_cta_and_hashtags_from_template(rig):
    rig["install"]([json.dumps({
        "title": "No CTA from the model",
        "beats": PACK_BEATS,
        "total_duration_sec": 10,
    })])
    pack = generators.generate_topic_pack(TEMPLATE, "any topic")
    assert pack["cta"] == TEMPLATE.cta
    assert pack["hashtags"] == TEMPLATE.hashtags


# ----------------------------------------------------------------------
# (c) Defensive beat parsing
# ----------------------------------------------------------------------
def test_topic_pack_drops_empty_narration_beats(rig):
    rig["install"]([json.dumps({
        "title": "Half empty",
        "beats": [
            {"start_sec": 0, "duration_sec": 5, "narration": "   ",
             "visual_prompt": "a scene with no words"},
            PACK_BEATS[0],
            "not even an object",
        ],
        "total_duration_sec": 10,
    })])
    pack = generators.generate_topic_pack(TEMPLATE, "any topic")
    assert len(pack["beats"]) == 1
    assert pack["beats"][0]["narration"] == PACK_BEATS[0]["narration"]


def test_topic_pack_with_no_usable_beats_is_a_hard_error(rig):
    rig["install"]([json.dumps({
        "title": "All empty",
        "beats": [{"start_sec": 0, "narration": "",
                   "visual_prompt": "nothing"}],
    })])
    with pytest.raises(RuntimeError):
        generators.generate_topic_pack(TEMPLATE, "any topic")


# ----------------------------------------------------------------------
# (d) The markdown production pack
# ----------------------------------------------------------------------
def test_format_production_pack_contents(rig):
    rig["install"]([PACK_RESPONSE])
    pack = generators.generate_topic_pack(TEMPLATE, "giant pancake day")
    md = generators.format_production_pack(
        TEMPLATE, "giant pancake day", pack)
    assert "# Gus and the Giant Pancake" in md
    assert "Paws & Plates — Restaurant Cats" in md
    assert "giant pancake day" in md
    assert PACK_BEATS[0]["visual_prompt"] in md
    assert "Beat 1 · 0:00–0:05" in md
    assert "The giant pancake" in md          # on-screen text
    assert "light playful music, low" in md   # music cue
    assert "## CTA" in md and "LIKE • SHARE • FOLLOW" in md
    assert "## Caption" in md and "Pancake day at Paws & Plates" in md
    assert "#CatsOfFacebook" in md


# ----------------------------------------------------------------------
# (e) End-to-end: template → topic → generate → auto-saved result
# ----------------------------------------------------------------------
def test_end_to_end_pack_auto_saves_onto_topic(rig, temp_db):
    master_prompt.save(TEMPLATE)
    topic = master_prompt.add_topic(TEMPLATE.name,
                                    "Gus tries to cook a giant pancake")
    assert topic.status == "new" and topic.result is None

    rig["install"]([PACK_RESPONSE])
    locked = master_prompt.load(TEMPLATE.name)
    pack = generators.generate_topic_pack(locked, topic.topic)
    assert master_prompt.save_topic_result(topic.id, pack) is True

    topics = master_prompt.list_topics(TEMPLATE.name)
    assert len(topics) == 1
    assert topics[0].status == "generated"
    assert topics[0].result == pack
    assert topics[0].result["beats"][1]["narration"].startswith("Gus takes")


# ----------------------------------------------------------------------
# (f) Malformed model output fails loudly in both generators
# ----------------------------------------------------------------------
def test_malformed_json_raises_in_both_generators(rig):
    rig["install"](["Sorry, I cannot help with that."])
    with pytest.raises(RuntimeError):
        generators.generate_template_from_niche("deep sea creatures")

    rig["install"](["{not valid json"])
    with pytest.raises(RuntimeError):
        generators.generate_topic_pack(TEMPLATE, "any topic")
