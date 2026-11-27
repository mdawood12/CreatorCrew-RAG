"""Tests for the per-template Topics system (Topics Step 1).

Offline: everything runs against a TEMP database — config.DB_PATH is
monkeypatched to a tmp_path file, because memory._conn() reads
config.DB_PATH at call time. The real storage/creator_memory.db is
never touched.

Covers: add + latest-first listing, strict per-template isolation,
case-insensitive duplicate detection, status changes (valid + invalid),
save_topic_result (stores the dict, flips status to 'generated'),
deletion, counting, and the template-delete cascade.

Run:  .venv/bin/python -m pytest tests/test_topics.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, master_prompt, memory          # noqa: E402
from src.schemas import MasterPromptTemplate, MasterTopic  # noqa: E402


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_topics.db"
    monkeypatch.setattr(config, "DB_PATH", db_file)
    memory.init_db()
    assert db_file.exists()
    return db_file


@pytest.fixture()
def two_templates(temp_db):
    master_prompt.save(MasterPromptTemplate(name="Alpha"))
    master_prompt.save(MasterPromptTemplate(name="Beta"))
    return ("Alpha", "Beta")


# ----------------------------------------------------------------------
# Add + ordering + counting
# ----------------------------------------------------------------------
def test_add_and_list_latest_first(two_templates):
    a, _ = two_templates
    t1 = master_prompt.add_topic(a, "first topic")
    t2 = master_prompt.add_topic(a, "second topic")
    assert isinstance(t1, MasterTopic)
    assert t1.status == "new" and t1.result is None
    assert t1.created_at and t1.updated_at

    topics = master_prompt.list_topics(a)
    assert [t.topic for t in topics] == ["second topic", "first topic"]
    assert topics[0].id == t2.id and topics[1].id == t1.id
    assert master_prompt.count_topics(a) == 2


def test_add_topic_strips_and_rejects_empty(two_templates):
    a, _ = two_templates
    t = master_prompt.add_topic(a, "  padded topic  ")
    assert t.topic == "padded topic"
    with pytest.raises(ValueError):
        master_prompt.add_topic(a, "   ")
    with pytest.raises(ValueError):
        master_prompt.add_topic(a, "")


# ----------------------------------------------------------------------
# Isolation — topics never leak across templates
# ----------------------------------------------------------------------
def test_topics_isolated_per_template(two_templates):
    a, b = two_templates
    master_prompt.add_topic(a, "alpha one")
    master_prompt.add_topic(a, "alpha two")
    master_prompt.add_topic(b, "beta one")

    assert [t.topic for t in master_prompt.list_topics(a)] == [
        "alpha two", "alpha one"]
    assert [t.topic for t in master_prompt.list_topics(b)] == ["beta one"]
    assert master_prompt.count_topics(a) == 2
    assert master_prompt.count_topics(b) == 1
    # Same text in another template is NOT a duplicate.
    assert master_prompt.topic_exists(b, "alpha one") is False
    master_prompt.add_topic(b, "alpha one")
    assert master_prompt.count_topics(b) == 2


# ----------------------------------------------------------------------
# Duplicate detection — case-insensitive, whitespace-tolerant
# ----------------------------------------------------------------------
def test_duplicate_detection_case_insensitive(two_templates):
    a, _ = two_templates
    master_prompt.add_topic(a, "Gus Cooks a Pancake")
    assert master_prompt.topic_exists(a, "gus cooks a pancake") is True
    assert master_prompt.topic_exists(a, "  GUS COOKS A PANCAKE ") is True
    assert master_prompt.topic_exists(a, "Gus cooks soup") is False
    found = memory.find_topic(a, "gus cooks a pancake")
    assert found is not None and found["topic"] == "Gus Cooks a Pancake"
    assert memory.find_topic(a, "missing") is None


# ----------------------------------------------------------------------
# Status changes
# ----------------------------------------------------------------------
def test_set_topic_status_valid_and_invalid(two_templates):
    a, _ = two_templates
    t = master_prompt.add_topic(a, "status topic")
    assert master_prompt.set_topic_status(t.id, "generated") is True
    assert memory.get_topic(t.id)["status"] == "generated"
    assert master_prompt.set_topic_status(t.id, "posted") is True
    assert memory.get_topic(t.id)["status"] == "posted"
    with pytest.raises(ValueError):
        master_prompt.set_topic_status(t.id, "bogus")
    # Unknown id: no crash, just False.
    assert master_prompt.set_topic_status(999999, "new") is False


# ----------------------------------------------------------------------
# save_topic_result — the hook generation (Step 2) will use
# ----------------------------------------------------------------------
def test_save_topic_result_stores_and_marks_generated(two_templates):
    a, _ = two_templates
    t = master_prompt.add_topic(a, "result topic")
    result = {"angle": "fresh angle", "beats": [{"narration": "hi"}]}
    assert master_prompt.save_topic_result(t.id, result) is True

    stored = memory.get_topic(t.id)
    assert stored["result"] == result
    assert stored["status"] == "generated"
    loaded = master_prompt.list_topics(a)[0]
    assert loaded.result == result and loaded.status == "generated"
    assert master_prompt.save_topic_result(999999, result) is False


# ----------------------------------------------------------------------
# Deletion + template cascade
# ----------------------------------------------------------------------
def test_delete_topic(two_templates):
    a, _ = two_templates
    t1 = master_prompt.add_topic(a, "keep me")
    t2 = master_prompt.add_topic(a, "delete me")
    assert master_prompt.delete_topic(t2.id) is True
    assert [t.topic for t in master_prompt.list_topics(a)] == ["keep me"]
    assert master_prompt.delete_topic(t2.id) is False
    assert memory.get_topic(t1.id) is not None


def test_template_delete_cascades_topics(two_templates):
    a, b = two_templates
    master_prompt.add_topic(a, "alpha topic")
    master_prompt.add_topic(b, "beta topic")

    assert master_prompt.delete(a) is True
    assert master_prompt.list_topics(a) == []
    assert master_prompt.count_topics(a) == 0
    # The other template and its topics are untouched.
    assert master_prompt.load(b) is not None
    assert [t.topic for t in master_prompt.list_topics(b)] == ["beta topic"]
    assert memory.delete_topics_for_template(b) == 1
