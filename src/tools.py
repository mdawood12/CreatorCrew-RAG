"""
tools.py — RAG retrieval tools + transcript/link helpers [Phase 4 support].

Transcript fallback chain [C5] — a single source is unreliable, so:
  1) youtube-transcript-api (fast, needs captions, can be IP-blocked)
  2) yt-dlp subtitles (manual or auto captions, fetched with the metadata)
  3) faster-whisper (local, free, works on the downloaded audio)
Article pages are extracted with trafilatura.
Retrieval tools support metadata filtering (doc_type / platform) so the
Critic can pull ONLY official policy chunks, and the Researcher can pull
ONLY viral-transcript chunks.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

from . import config
from .config import logger


# ---------------------------------------------------------------------------
# RAG retrieval
# ---------------------------------------------------------------------------
def retrieve(query: str, k: int = config.TOP_K,
             doc_type: str | None = None,
             platform: str | None = None) -> list[dict]:
    """Similarity search with optional metadata filters."""
    from .ingest import get_vectorstore
    store = get_vectorstore()
    where = None
    filters = {}
    if doc_type:
        filters["doc_type"] = doc_type
    if platform:
        filters["platform"] = platform
    if len(filters) == 1:
        where = filters
    elif len(filters) > 1:
        where = {"$and": [{k_: v} for k_, v in filters.items()]}
    docs = store.similarity_search(query, k=k, filter=where)
    return [{"text": d.page_content, "metadata": d.metadata} for d in docs]


def format_context(chunks: list[dict]) -> tuple[str, list[str]]:
    """Turn retrieved chunks into prompt context + a citation list."""
    lines, citations = [], []
    for i, c in enumerate(chunks, 1):
        src = c["metadata"].get("source", "unknown")
        lines.append(f"[{i}] ({src}) {c['text']}")
        if src not in citations:
            citations.append(src)
    return "\n\n".join(lines), citations


# ---------------------------------------------------------------------------
# Transcript helpers
# ---------------------------------------------------------------------------
def youtube_id(url_or_id: str) -> str | None:
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", url_or_id)
    if m:
        return m.group(1)
    return url_or_id if re.fullmatch(r"[A-Za-z0-9_-]{11}", url_or_id) else None


def _segments_to_text(segments: list[dict]) -> str:
    return " ".join(s.get("text", "") for s in segments).strip()


def transcript_via_api(video_id: str) -> list[dict] | None:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        fetched = YouTubeTranscriptApi().fetch(video_id, languages=["en"])
        return [{"text": s.text, "start": s.start, "duration": s.duration}
                for s in fetched]
    except Exception as e:
        logger.warning("transcript-api failed for %s: %s", video_id, e)
        return None


def transcript_via_ytdlp(url: str) -> list[dict] | None:
    try:
        with tempfile.TemporaryDirectory() as td:
            out = str(Path(td) / "subs")
            subprocess.run(
                ["yt-dlp", "--skip-download", "--write-auto-subs",
                 "--write-subs", "--sub-langs", "en.*", "--sub-format", "json3",
                 "-o", out, url],
                capture_output=True, timeout=120, check=False)
            files = list(Path(td).glob("*.json3"))
            if not files:
                return None
            data = json.loads(files[0].read_text(encoding="utf-8"))
            segs = []
            for ev in data.get("events", []):
                parts = ev.get("segs") or []
                text = "".join(p.get("utf8", "") for p in parts).strip()
                if text:
                    segs.append({"text": text,
                                 "start": ev.get("tStartMs", 0) / 1000.0,
                                 "duration": ev.get("dDurationMs", 0) / 1000.0})
            return segs or None
    except Exception as e:
        logger.warning("yt-dlp subtitles failed for %s: %s", url, e)
        return None


def transcript_via_whisper(url_or_file: str) -> list[dict] | None:
    """Last resort: download audio (yt-dlp) or read the local file, then
    transcribe locally with faster-whisper — free, no captions needed."""
    try:
        from faster_whisper import WhisperModel
        src = url_or_file
        tmp = None
        if url_or_file.startswith("http"):
            tmp = tempfile.mkdtemp()
            audio = str(Path(tmp) / "audio.m4a")
            subprocess.run(["yt-dlp", "-f", "bestaudio", "-o", audio, url_or_file],
                           capture_output=True, timeout=600, check=False)
            if not Path(audio).exists():
                return None
            src = audio
        model = WhisperModel("tiny", device="cpu", compute_type="int8")
        segments, _info = model.transcribe(src, beam_size=1)
        segs = [{"text": s.text.strip(), "start": s.start,
                 "duration": s.end - s.start} for s in segments
                if s.text.strip()]
        return segs or None
    except Exception as e:
        logger.warning("whisper transcription failed: %s", e)
        return None


def get_transcript(url_or_file: str) -> dict | None:
    """Full fallback chain. Returns {text, segments, method} or None."""
    vid = youtube_id(url_or_file)
    if vid:
        for name, fn in (("transcript-api", lambda: transcript_via_api(vid)),
                         ("yt-dlp-subs", lambda: transcript_via_ytdlp(url_or_file))):
            segs = fn()
            if segs:
                logger.info("Transcript via %s (%d segments)", name, len(segs))
                return {"text": _segments_to_text(segs), "segments": segs,
                        "method": name}
    segs = transcript_via_whisper(url_or_file)
    if segs:
        return {"text": _segments_to_text(segs), "segments": segs,
                "method": "whisper"}
    return None


def extract_article(url: str) -> str | None:
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        return trafilatura.extract(downloaded) if downloaded else None
    except Exception as e:
        logger.warning("article extraction failed for %s: %s", url, e)
        return None
