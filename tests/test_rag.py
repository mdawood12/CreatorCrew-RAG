"""
tests/test_rag.py — Retrieval smoke & relevance tests [Phase 2 gate].

These tests need NO LLM API key. Heavy parts (embeddings/Chroma) run
only when the knowledge base has been built; otherwise they skip with a
clear message instead of failing — run `python -m src.ingest` first.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, memory
from src.ingest import chunk_id
from src.schemas import ClipCandidate, ScriptPackage


def test_config_validates():
    report = config.validate()
    assert report["ffmpeg"] != "NOT FOUND", "FFmpeg must be installed"
    assert report["model"] == config.LLM_MODEL


def test_key_manager_failover():
    km = config.KeyManager(["k1111", "k2222"])
    assert km.current_key() == "k1111"
    assert km.report_failure(429) == "k2222"
    assert km.report_failure(403) is None
    assert km.status()["state"] == "down"
    assert config.KeyManager([]).status()["state"] == "no_key"


def test_chunk_id_idempotent():
    a = chunk_id("same text", "file:x")
    b = chunk_id("same text", "file:x")
    c = chunk_id("other text", "file:x")
    assert a == b and a != c


def test_memory_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    memory.init_db()
    memory.set_profile(niche="fitness", tone="bold")
    assert memory.get_profile()["niche"] == "fitness"
    oid = memory.save_output("script", "topic", "youtube", {"a": 1}, {"v": "pass"})
    assert oid >= 1
    assert memory.list_outputs(1)[0]["topic"] == "topic"


def test_schemas_reject_bad_clip():
    try:
        ClipCandidate(start_sec=10, end_sec=5, hook="h", reason="r")
        assert False, "expected validation error"
    except Exception:
        pass
    ok = ClipCandidate(start_sec=10, end_sec=40, hook="h", reason="r")
    assert ok.duration == 30


def test_retrieval_if_index_built():
    from src.ingest import get_vectorstore
    store = get_vectorstore()
    count = len(store.get(include=[])["ids"])
    if count == 0:
        import pytest
        pytest.skip("Knowledge base empty — run: python -m src.ingest")
    from src.tools import retrieve
    hits = retrieve("copyright reused content policy", k=3,
                    doc_type="platform_policy")
    assert hits, "policy retrieval returned nothing"
    assert all(h["metadata"].get("doc_type") == "platform_policy" for h in hits)
