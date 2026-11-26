"""Tests for the splitter's URL policy (docs/AUDIT.md Finding 1).

splitter._download historically ran yt-dlp on ANY http URL. It must
now refuse watch-page hosts with the same policy as the editing
intake (the host list lives only in src/editing/intake.py), while
direct media URLs still download as before. Offline throughout:
subprocess.run is monkeypatched, yt-dlp is never executed.

Run:  .venv/bin/python -m pytest tests/test_splitter_url_policy.py -q
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import splitter                # noqa: E402

YOUTUBE_URL = "https://www.youtube.com/watch?v=abc123XYZ"
YOUTU_BE_URL = "https://youtu.be/abc123XYZ"
DIRECT_URL = "https://example.com/video.mp4"


def _no_run(monkeypatch):
    """Patch subprocess.run so any call fails the test loudly."""
    calls = []

    def _boom(cmd, **kwargs):
        calls.append(cmd)
        raise AssertionError("subprocess.run must not be called")

    monkeypatch.setattr(subprocess, "run", _boom)
    return calls


# --- watch-page hosts are refused before any subprocess ------------------

def test_download_refuses_youtube_watch_url(tmp_path, monkeypatch):
    calls = _no_run(monkeypatch)
    with pytest.raises(ValueError, match="My video URL"):
        splitter._download(YOUTUBE_URL, tmp_path / "source.mp4")
    assert calls == []


def test_download_refuses_youtu_be_short_link(tmp_path, monkeypatch):
    calls = _no_run(monkeypatch)
    with pytest.raises(ValueError, match="My video URL"):
        splitter._download(YOUTU_BE_URL, tmp_path / "source.mp4")
    assert calls == []


# --- direct media URLs still reach the downloader -------------------------

def test_download_allows_direct_media_url(tmp_path, monkeypatch):
    seen = {}

    def _fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        dest = Path(cmd[cmd.index("-o") + 1])
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake-media")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", _fake_run)
    dest = tmp_path / "source.mp4"
    result = splitter._download(DIRECT_URL, dest)
    assert result == dest
    assert result.exists()
    assert seen["cmd"][-1] == DIRECT_URL


# --- split_video refuses a watch URL before downloading -------------------

def test_split_video_refuses_watch_url(tmp_path, monkeypatch):
    calls = _no_run(monkeypatch)
    monkeypatch.setattr(splitter.config, "SHORTS_DIR", tmp_path / "shorts")
    with pytest.raises(ValueError, match="My video URL"):
        splitter.split_video(YOUTUBE_URL, "own", "my own channel upload")
    assert calls == []
