"""Tests for the MODEL BACKUP CHAIN [C16] in src/config.py.

Offline: config.get_llm is replaced by a fake that records which model
it was asked to build, config.KEY_MANAGER by a stub that counts key
rotations, and time.sleep is neutralised. Covers: chain parsing
(default order, LLM_MODELS override, dedupe); a model error advancing
to the next model in order; a 429 rotating the key on the SAME model;
success on the second model; the whole chain failing as one
RuntimeError; a non-retryable error raising immediately; and an
exhausted key pool keeping today's "All API keys failed" contract.

Run:  .venv/bin/python -m pytest tests/test_model_chain.py -q
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config                  # noqa: E402

CHAIN = ["model-one", "model-two", "model-three"]


class _FakeLLM:
    """Stands in for the chat model; carries the model name it was
    built with so make_call can fail per model."""

    def __init__(self, model: str):
        self.model = model


class _KeyStub:
    """KEY_MANAGER stand-in: counts rotations, serves a fixed pool."""

    def __init__(self, pool_alive: bool = True):
        self.rotations = 0
        self._pool_alive = pool_alive

    def report_failure(self, status):
        self.rotations += 1
        return "next-key" if self._pool_alive else None


@pytest.fixture()
def rig(monkeypatch):
    """Patch the config seams; return the shared call log."""
    state = {"built": [], "keys": _KeyStub()}
    monkeypatch.setattr(config, "MODEL_CHAIN", list(CHAIN))
    monkeypatch.setattr(config, "KEY_MANAGER", state["keys"])
    monkeypatch.setattr(time, "sleep", lambda _s: None)

    def fake_get_llm(temperature=config.TEMP_SCRIPT, model=None):
        state["built"].append(model)
        return _FakeLLM(model or config.LLM_MODEL)

    monkeypatch.setattr(config, "get_llm", fake_get_llm)
    return state


def _caller(failures: dict[str, list[Exception]]):
    """make_call that raises the queued errors per model, then
    returns a result naming the model that finally served it."""
    queues = {m: list(errs) for m, errs in failures.items()}

    def make_call(llm):
        queue = queues.get(llm.model, [])
        if queue:
            raise queue.pop(0)
        return f"served-by-{llm.model}"

    return make_call


# ----------------------------------------------------------------------
# Chain parsing
# ----------------------------------------------------------------------

def test_default_chain_is_primary_then_fallbacks(monkeypatch):
    monkeypatch.delenv("LLM_MODELS", raising=False)
    chain = config._parse_model_chain()
    expected = [config.LLM_MODEL, "gemini-2.5-flash",
                "gemini-2.5-flash-lite"]
    deduped = list(dict.fromkeys(expected))
    assert chain == deduped
    assert chain[0] == config.LLM_MODEL


def test_llm_models_override_parsing(monkeypatch):
    monkeypatch.setenv("LLM_MODELS", " alpha , beta ,gamma ")
    assert config._parse_model_chain() == ["alpha", "beta", "gamma"]


def test_chain_dedupes_preserving_order(monkeypatch):
    monkeypatch.setenv("LLM_MODELS", "a,b,a,,c,b")
    assert config._parse_model_chain() == ["a", "b", "c"]


def test_module_chain_matches_parser():
    assert config.MODEL_CHAIN == config._parse_model_chain()
    assert config.MODEL_CHAIN[0] == config.LLM_MODEL


# ----------------------------------------------------------------------
# Failover behaviour
# ----------------------------------------------------------------------

def test_model_error_advances_to_next_model_in_order(rig):
    make_call = _caller({"model-one": [Exception(
        "404 NOT_FOUND: models/model-one is not found for API version")]})
    result = config.call_llm_with_failover(make_call)
    assert result == "served-by-model-two"
    assert rig["built"] == ["model-one", "model-two"]
    assert rig["keys"].rotations == 0  # a model error never rotates keys


def test_success_on_second_model_returns_its_result(rig):
    make_call = _caller({"model-one": [Exception(
        "503 Service Unavailable: the model is overloaded")]})
    result = config.call_llm_with_failover(make_call)
    assert result == "served-by-model-two"
    assert rig["built"] == ["model-one", "model-two"]


def test_quota_rotates_key_without_changing_model(rig):
    make_call = _caller({"model-one": [Exception(
        "429 ResourceExhausted: quota exceeded for this key")]})
    result = config.call_llm_with_failover(make_call)
    assert result == "served-by-model-one"
    assert rig["built"] == ["model-one", "model-one"]
    assert rig["keys"].rotations == 1


def test_all_models_failing_raises_runtime_error(rig):
    err = Exception("404: model not found")
    make_call = _caller({m: [err] for m in CHAIN})
    with pytest.raises(RuntimeError) as excinfo:
        config.call_llm_with_failover(make_call)
    assert "All API keys failed" in str(excinfo.value)
    # Each model tried exactly once — a model error leaves the model
    # at once instead of burning the per-model attempts on it.
    assert rig["built"] == CHAIN
    assert rig["keys"].rotations == 0


def test_non_retryable_error_raises_immediately(rig):
    def make_call(llm):
        raise ValueError("bad prompt: unsupported content")

    with pytest.raises(ValueError):
        config.call_llm_with_failover(make_call)
    assert rig["built"] == ["model-one"]  # the chain is never walked
    assert rig["keys"].rotations == 0


def test_exhausted_key_pool_raises_without_walking_chain(rig):
    rig["keys"]._pool_alive = False
    make_call = _caller({"model-one": [Exception("429 quota exceeded")]})
    with pytest.raises(RuntimeError) as excinfo:
        config.call_llm_with_failover(make_call)
    assert "All API keys failed" in str(excinfo.value)
    assert rig["built"] == ["model-one"]
    assert rig["keys"].rotations == 1
