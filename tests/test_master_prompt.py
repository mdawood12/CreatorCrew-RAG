"""Tests for the Master Prompt lock system (Step 1).

Offline: the character parser/formatter are pure functions, and the
storage round-trip runs against a TEMP database — config.DB_PATH is
monkeypatched to a tmp_path file, because memory._conn() reads
config.DB_PATH at call time. The real storage/creator_memory.db is
never touched.

Run:  .venv/bin/python -m pytest tests/test_master_prompt.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, master_prompt, memory          # noqa: E402
from src.schemas import MasterPromptTemplate           # noqa: E402


# ----------------------------------------------------------------------
# (a) Character parsing / formatting
# ----------------------------------------------------------------------
def test_parse_characters_all_line_shapes():
    text = (
        "Gus — fluffy orange tabby, green eyes, restaurant manager\n"
        "Pepper: black-and-white tuxedo cat, the chef\n"
        "Smokey\n"
        "\n"
        "   \n"
        "  Mochi — white cat, cashier  \n"
    )
    chars = master_prompt.parse_characters(text)
    assert chars == [
        {"name": "Gus",
         "description": "fluffy orange tabby, green eyes, restaurant manager"},
        {"name": "Pepper",
         "description": "black-and-white tuxedo cat, the chef"},
        {"name": "Smokey", "description": ""},
        {"name": "Mochi", "description": "white cat, cashier"},
    ]


def test_parse_characters_em_dash_wins_over_colon():
    # "—" is checked first even when a ":" appears earlier in the line.
    chars = master_prompt.parse_characters("Note: Gus — the manager")
    assert chars == [{"name": "Note: Gus", "description": "the manager"}]


def test_format_parse_round_trip():
    chars = [
        {"name": "Gus", "description": "fluffy orange tabby, green eyes"},
        {"name": "Pepper", "description": "tuxedo cat: head chef"},
        {"name": "Smokey", "description": ""},
    ]
    text = master_prompt.format_characters(chars)
    assert text == ("Gus — fluffy orange tabby, green eyes\n"
                    "Pepper — tuxedo cat: head chef\n"
                    "Smokey")
    assert master_prompt.parse_characters(text) == chars


def test_parse_characters_empty_text():
    assert master_prompt.parse_characters("") == []
    assert master_prompt.parse_characters("\n \n") == []
    assert master_prompt.format_characters([]) == ""


# ----------------------------------------------------------------------
# (b) Schema defaults
# ----------------------------------------------------------------------
def test_template_defaults():
    tpl = MasterPromptTemplate(name="Bare")
    assert tpl.characters == []
    assert tpl.negative_prompt  # non-empty safety default
    assert "no watermark" in tpl.negative_prompt
    assert tpl.beat_count == 0  # 0 = auto
    assert tpl.target_format == "Reel 60s"
    assert tpl.language == "English"


# ----------------------------------------------------------------------
# (c) + (d) Storage round-trip on a TEMP database
# ----------------------------------------------------------------------
@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_memory.db"
    monkeypatch.setattr(config, "DB_PATH", db_file)
    memory.init_db()
    assert db_file.exists()
    return db_file


def _sample_template() -> MasterPromptTemplate:
    return MasterPromptTemplate(
        name="Paws & Plates",
        characters=[{"name": "Gus", "description": "fluffy orange tabby"},
                    {"name": "Pepper", "description": "tuxedo chef"}],
        visual_style="cinematic realistic, cozy diner, vertical 9:16",
        target_format="Reel 60s",
        beat_count=8,
        cta="Follow for more!",
        hashtags="#cats #reels")


def test_storage_round_trip(temp_db):
    assert master_prompt.list_names() == []

    saved = master_prompt.save(_sample_template())
    assert saved.name == "Paws & Plates"
    assert master_prompt.list_names() == ["Paws & Plates"]

    loaded = master_prompt.load("Paws & Plates")
    assert loaded is not None
    assert loaded.characters[0].name == "Gus"
    assert loaded.characters[1].description == "tuxedo chef"
    assert loaded.beat_count == 8
    assert loaded.cta == "Follow for more!"

    # Upsert: saving the same name updates instead of duplicating.
    updated = _sample_template()
    updated.beat_count = 10
    master_prompt.save(updated)
    assert master_prompt.list_names() == ["Paws & Plates"]
    assert master_prompt.load("Paws & Plates").beat_count == 10

    # A second template sorts alongside the first.
    master_prompt.save(MasterPromptTemplate(name="Alpha"))
    assert master_prompt.list_names() == ["Alpha", "Paws & Plates"]

    assert master_prompt.delete("Paws & Plates") is True
    assert master_prompt.load("Paws & Plates") is None
    assert master_prompt.list_names() == ["Alpha"]
    assert master_prompt.delete("Paws & Plates") is False


def test_load_missing_template_returns_none(temp_db):
    assert master_prompt.load("no-such-template") is None
    assert memory.get_template("no-such-template") is None
