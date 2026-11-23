"""
tests/test_phase0.py — Phase 0 audit-fix proofs (no API key needed).

1. The Critic fails CLOSED: a forced unparseable Critic output must
   produce compliance_ok=False / verdict != "pass" / a NEEDS REVIEW
   issue — never the old silent pass.
2. The placeholder filter rejects obvious placeholder keys generally
   (not just one literal string) while keeping token-shaped keys.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import agents, config


class _BadStructured:
    def invoke(self, prompt):
        raise RuntimeError("forced unparseable critic output")


class _BadLLM:
    def with_structured_output(self, schema):
        return _BadStructured()


def test_critic_fails_closed(monkeypatch):
    monkeypatch.setattr(config, "call_llm_with_failover",
                        lambda fn: fn(_BadLLM()))
    state = {"draft": {"topic": "t", "youtube": {}, "facebook": {}},
             "source_text": "", "policy_context": ""}
    out = agents.critic_node(state)
    critic = out["critic"]
    assert critic["compliance_ok"] is False, critic
    assert critic["verdict"] != "pass", critic
    assert any("NEEDS REVIEW" in i for i in critic["issues"]), critic


def test_placeholder_filter(monkeypatch):
    real_looking = "AQ.Ab8RN6KxYz1234567890TokenShapedValue99"
    monkeypatch.setenv(
        "GOOGLE_API_KEYS",
        "apni-key, your-key-here, placeholder-value, "
        "insert_api_key_here, changeme123, " + real_looking)
    km = config.KeyManager()
    assert km.keys == [real_looking], km.keys
    monkeypatch.setenv("GOOGLE_API_KEYS", "apni-key, your-key")
    km2 = config.KeyManager()
    assert km2.has_keys is False
    assert km2.status()["state"] == "no_key"


def test_is_placeholder_general():
    f = config.KeyManager._is_placeholder
    assert f("apni-key") and f("YOUR_API_KEY") and f("xx-placeholder-xx")
    assert f("short")
    assert not f("AQ.Ab8RN6KxYz1234567890TokenShapedValue99")
