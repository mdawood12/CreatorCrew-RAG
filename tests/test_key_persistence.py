"""Tests for KEY-POOL MEMORY [C17] in src/config.py — dead-key marks
persist across restarts (audit finding 6.3c).

Offline: every test points KEY_STATE_PATH at a tmp file and builds
KeyManager with fake keys, so nothing touches the real state file or
the network. Covers: a dead key stays dead across a simulated restart;
a 429 mark older than 24 h revives (daily quota reset) while a recent
one does not; a 403 mark never revives; a corrupt state file starts
clean; the state file never contains a raw key; and a pool whose keys
are all marked dead still hands out a key to try.

Run:  .venv/bin/python -m pytest tests/test_key_persistence.py -q
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config                  # noqa: E402

KEY_A = "alphaTokenValue1111111111"
KEY_B = "bravoTokenValue2222222222"
KEY_C = "charlieTokenValue3333333333"
POOL = [KEY_A, KEY_B, KEY_C]
HOUR = 60 * 60


@pytest.fixture()
def state_path(tmp_path, monkeypatch):
    """Point the key-state file at a fresh tmp location."""
    path = tmp_path / "key_state.json"
    monkeypatch.setenv("KEY_STATE_PATH", str(path))
    return path


def _write_state(path: Path, marks: dict[str, tuple[int, float]]) -> None:
    """Write a state file by hand: {key: (status, failed_at)}."""
    path.write_text(json.dumps({
        config._key_fingerprint(key): {"status": status,
                                       "failed_at": failed_at}
        for key, (status, failed_at) in marks.items()
    }), encoding="utf-8")


# ----------------------------------------------------------------------
# Persistence across a simulated restart
# ----------------------------------------------------------------------

def test_missing_state_file_starts_clean(state_path):
    assert not state_path.exists()
    km = config.KeyManager(POOL)
    assert km.dead == set()
    assert km.current_key() == KEY_A


def test_dead_key_survives_restart(state_path):
    km = config.KeyManager(POOL)
    assert km.current_key() == KEY_A
    assert km.report_failure(429) == KEY_B
    assert state_path.exists()

    restarted = config.KeyManager(POOL)   # a fresh process, same pool
    assert restarted.dead == {0}
    assert restarted.current_key() == KEY_B


def test_403_mark_survives_restart(state_path):
    km = config.KeyManager(POOL)
    assert km.report_failure(403) == KEY_B

    restarted = config.KeyManager(POOL)
    assert restarted.dead == {0}
    assert restarted.current_key() == KEY_B


# ----------------------------------------------------------------------
# Expiry semantics — 429 revives after 24 h, 403 never does
# ----------------------------------------------------------------------

def test_429_older_than_24h_revives(state_path):
    _write_state(state_path,
                 {KEY_A: (429, time.time() - 25 * HOUR)})
    km = config.KeyManager(POOL)
    assert km.dead == set()
    assert km.current_key() == KEY_A


def test_recent_429_stays_dead(state_path):
    _write_state(state_path,
                 {KEY_A: (429, time.time() - 1 * HOUR)})
    km = config.KeyManager(POOL)
    assert km.dead == {0}
    assert km.current_key() == KEY_B


def test_403_never_revives(state_path):
    _write_state(state_path,
                 {KEY_A: (403, time.time() - 30 * 24 * HOUR)})
    km = config.KeyManager(POOL)
    assert km.dead == {0}
    assert km.current_key() == KEY_B


# ----------------------------------------------------------------------
# Robustness — a broken state file can never break the app
# ----------------------------------------------------------------------

def test_corrupt_state_file_starts_clean(state_path):
    state_path.write_text("{this is not json!!", encoding="utf-8")
    km = config.KeyManager(POOL)
    assert km.dead == set()
    assert km.current_key() == KEY_A

    state_path.write_text("[1, 2, 3]", encoding="utf-8")  # not a dict
    km = config.KeyManager(POOL)
    assert km.dead == set()
    assert km.current_key() == KEY_A


# ----------------------------------------------------------------------
# Security — raw keys are never written to disk
# ----------------------------------------------------------------------

def test_state_file_never_contains_raw_keys(state_path):
    km = config.KeyManager(POOL)
    assert km.report_failure(429) == KEY_B
    assert km.report_failure(403) == KEY_C

    blob = state_path.read_bytes()
    for key in POOL:
        assert key.encode() not in blob
    saved = json.loads(blob)
    assert set(saved) == {config._key_fingerprint(KEY_A),
                          config._key_fingerprint(KEY_B)}
    assert saved[config._key_fingerprint(KEY_A)]["status"] == 429
    assert saved[config._key_fingerprint(KEY_B)]["status"] == 403


# ----------------------------------------------------------------------
# All keys dead — selection still hands out a key to try
# ----------------------------------------------------------------------

def test_all_keys_dead_still_hands_out_a_key(state_path):
    now = time.time()
    _write_state(state_path, {KEY_A: (403, now), KEY_B: (403, now)})
    km = config.KeyManager([KEY_A, KEY_B])
    assert km.current_key() == KEY_A     # a key to try, not None


def test_exhausted_pool_still_serves_after_restart(state_path):
    km = config.KeyManager([KEY_A, KEY_B])
    assert km.report_failure(429) == KEY_B
    assert km.report_failure(429) is None        # pool exhausted

    restarted = config.KeyManager([KEY_A, KEY_B])
    assert restarted.current_key() is not None   # never worse than today
