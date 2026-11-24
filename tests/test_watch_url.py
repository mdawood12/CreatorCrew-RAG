"""Tests for the own-video watch-URL intake route (intake.py).

Offline: yt-dlp is never called — _download_watch is monkeypatched
to drop in a tiny ffmpeg-made mp4, exactly as the real download
would. Covers the rights gate, watch-URL validation, library
storage (origin_kind='watch-url') and remove_from_library (the
save-space auto-delete the UI uses after rendering).

Run:  .venv/bin/python -m pytest tests/test_watch_url.py -q
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.editing import intake          # noqa: E402

YOUTUBE_URL = "https://www.youtube.com/watch?v=abc123XYZ"


@pytest.fixture()
def library(tmp_path, monkeypatch):
    lib = tmp_path / "library"
    lib.mkdir()
    monkeypatch.setattr(intake, "LIBRARY_DIR", lib)
    monkeypatch.setattr(intake, "INDEX_PATH", lib / "index.json")
    return lib


def _tiny_mp4(path: Path) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=10",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
         "-shortest", "-c:v", "libx264", "-c:a", "aac", str(path)],
        check=True, capture_output=True, timeout=120)
    return path


def _fake_download(tiny: Path):
    def _dl(url: str, dest_dir: Path):
        dest = dest_dir / "_watch.mp4"
        dest.write_bytes(tiny.read_bytes())
        return dest, "My Own Test Video"
    return _dl


# --- validate_watch_url -------------------------------------------------

def test_watch_url_accepts_youtube():
    assert intake.validate_watch_url(YOUTUBE_URL) == YOUTUBE_URL
    assert intake.validate_watch_url("https://youtu.be/abc123XYZ")


def test_watch_url_refuses_direct_media_file():
    with pytest.raises(ValueError):
        intake.validate_watch_url("https://example.com/my-video.mp4")


def test_watch_url_refuses_unknown_host():
    with pytest.raises(ValueError):
        intake.validate_watch_url("https://example.com/watch?v=1")
    with pytest.raises(ValueError):
        intake.validate_watch_url("https://vimeo.com.evil.com/123")


def test_watch_url_refuses_garbage():
    with pytest.raises(ValueError):
        intake.validate_watch_url("not a url")


# --- the rights gate runs before any download ---------------------------

def test_gate_blocks_bad_rights_before_download(library, monkeypatch):
    def _boom(url, dest_dir):
        raise AssertionError("download must not be attempted")
    monkeypatch.setattr(intake, "_download_watch", _boom)
    with pytest.raises(ValueError):
        intake.add_watch_url_to_library(YOUTUBE_URL, "", "my video")
    with pytest.raises(ValueError):
        intake.add_watch_url_to_library(YOUTUBE_URL, "own", "x")


def test_gate_blocks_non_watch_url(library, monkeypatch):
    monkeypatch.setattr(intake, "_download_watch",
                        _fake_download(_tiny_mp4(library / "t.mp4")))
    with pytest.raises(ValueError):
        intake.add_watch_url_to_library(
            "https://example.com/my-video.mp4", "own", "my own file")


# --- happy path + save-space removal -------------------------------------

def test_add_and_remove_watch_entry(library, monkeypatch):
    tiny = _tiny_mp4(library / "seed.mp4")
    monkeypatch.setattr(intake, "_download_watch", _fake_download(tiny))

    entry = intake.add_watch_url_to_library(
        YOUTUBE_URL, "own", "My own channel upload, Nov 2026")
    assert entry["origin_kind"] == "watch-url"
    assert entry["source"] == YOUTUBE_URL
    assert entry["rights"] == "own"
    assert entry["name"] == "My Own Test Video"
    assert Path(entry["path"]).exists()
    assert entry["duration"] > 0
    # the temp download was cleaned up by the store step
    assert not (library / "_watch.mp4").exists()
    assert any(i["id"] == entry["id"] for i in intake.list_library())

    assert intake.remove_from_library(entry["id"]) is True
    assert not Path(entry["path"]).exists()
    assert intake.list_library() == []
    assert intake.remove_from_library(entry["id"]) is False
