"""
memory.py — Long-term memory in SQLite [Phase 3, schema C9].

Two tables:
- creator_profile(key, value): niche, audience, tone, channel name.
- outputs(...): every generated package + critic report (History tab).

Short-term/session memory is separate: LangGraph's MemorySaver in
agents.py. This module is deliberately dependency-light (stdlib sqlite3)
and is the ONLY place that talks to the database, so a future move to
Postgres is a one-module change (architect addendum).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from . import config

PROFILE_KEYS = ("niche", "audience", "tone", "channel_name")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS creator_profile(
            key TEXT PRIMARY KEY, value TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS outputs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT, kind TEXT, topic TEXT, platform TEXT,
            content_json TEXT, critic_json TEXT)""")


def get_profile() -> dict:
    init_db()
    with _conn() as c:
        rows = c.execute("SELECT key, value FROM creator_profile").fetchall()
    profile = {k: "" for k in PROFILE_KEYS}
    profile.update({r["key"]: r["value"] for r in rows})
    return profile


def set_profile(**fields) -> dict:
    init_db()
    with _conn() as c:
        for k, v in fields.items():
            if k in PROFILE_KEYS and v is not None:
                c.execute("INSERT INTO creator_profile(key, value) VALUES(?,?) "
                          "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                          (k, str(v)))
    return get_profile()


def save_output(kind: str, topic: str, platform: str,
                content: dict, critic: dict | None = None) -> int:
    init_db()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO outputs(created_at, kind, topic, platform, "
            "content_json, critic_json) VALUES(?,?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), kind, topic, platform,
             json.dumps(content, ensure_ascii=False),
             json.dumps(critic or {}, ensure_ascii=False)))
        return int(cur.lastrowid)


def list_outputs(limit: int = 20) -> list[dict]:
    init_db()
    with _conn() as c:
        rows = c.execute("SELECT * FROM outputs ORDER BY id DESC LIMIT ?",
                         (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["content"] = json.loads(d.pop("content_json") or "{}")
        d["critic"] = json.loads(d.pop("critic_json") or "{}")
        out.append(d)
    return out


def stats() -> dict:
    init_db()
    with _conn() as c:
        scripts = c.execute("SELECT COUNT(*) n FROM outputs WHERE kind='script'").fetchone()["n"]
        transforms = c.execute("SELECT COUNT(*) n FROM outputs WHERE kind='transform'").fetchone()["n"]
        clips = c.execute("SELECT COUNT(*) n FROM outputs WHERE kind='clip'").fetchone()["n"]
    return {"scripts": scripts, "transforms": transforms, "clips": clips}


if __name__ == "__main__":
    init_db()
    print("profile:", set_profile(niche="test", tone="bold"))
    print("saved id:", save_output("script", "demo topic", "youtube",
                                   {"ok": True}, {"verdict": "pass"}))
    print("stats:", stats())
