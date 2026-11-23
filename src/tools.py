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


def _valid_words(seg) -> list[dict]:
    """Defensively extract word timings from a faster-whisper segment
    [VIRALCUT Rule 2]: NEVER assume seg.words exists, is non-empty, or
    that its items carry start/end — filter strictly."""
    words = []
    for w in (getattr(seg, "words", None) or []):
        if w is None:
            continue
        start = getattr(w, "start", None)
        end = getattr(w, "end", None)
        text = (getattr(w, "word", "") or "").strip()
        if start is None or end is None or not text:
            continue
        words.append({"text": text, "start": float(start),
                      "end": float(end)})
    return words


def _synthetic_words(text: str, start: float, end: float) -> list[dict]:
    """Synthesize word timings by interpolating word lengths across
    the segment duration — the fallback when word-level (DTW)
    alignment fails on noisy audio or silence. Every synthesized
    word is flagged "approximate": True — these timings are an
    interpolation, NOT real word alignment, and must never be
    presented as such."""
    toks = text.split()
    if not toks:
        return []
    total = sum(len(t) for t in toks) or 1
    dur = max(float(end) - float(start), 0.0)
    out, t = [], float(start)
    for tok in toks:
        step = dur * len(tok) / total
        out.append({"text": tok, "start": round(t, 3),
                    "end": round(t + step, 3), "approximate": True})
        t += step
    return out


def word_timings_label(segments: list[dict]) -> str:
    """Honest label for a transcript's word timings, for sidecars/UI:
    "approximate (interpolated)" if any segment's word timings were
    synthesized by the fallback, "word-level" if real word timings
    are present, else "segment-level (no word timings)"."""
    if any(s.get("words_approximate") for s in segments):
        return "approximate (interpolated)"
    if any(s.get("words") for s in segments):
        return "word-level"
    return "segment-level (no word timings)"


def _whisper_segments(model, src: str) -> list[dict]:
    """Transcribe with word timestamps (greedy decoding: beam_size=1,
    the model's defaults are temperature 0). If DTW alignment raises
    — possibly mid-iteration — discard the partial result and retry
    with word_timestamps=False + synthetic word timings [Rule 2].
    Segment dicts gain a "words" list; text/start/duration are
    exactly as before, so existing callers are unaffected."""
    try:
        segments, _info = model.transcribe(src, beam_size=1,
                                           word_timestamps=True)
        out = []
        for s in segments:
            text = s.text.strip()
            if not text:
                continue
            real_words = _valid_words(s)
            seg = {"text": text, "start": s.start,
                   "duration": s.end - s.start,
                   "words": real_words or _synthetic_words(text, s.start,
                                                           s.end)}
            if not real_words:
                # No usable DTW alignment for this segment — its word
                # timings are interpolated, and are labelled as such.
                seg["words_approximate"] = True
            out.append(seg)
        if out:
            return out
        logger.warning("whisper produced no segments with word "
                       "timestamps; retrying without them")
    except Exception as e:
        logger.warning("whisper word alignment failed (%s); falling "
                       "back to synthetic word timings", e)
    segments, _info = model.transcribe(src, beam_size=1,
                                       word_timestamps=False)
    out = []
    for s in segments:
        text = s.text.strip()
        if text:
            out.append({"text": text, "start": s.start,
                        "duration": s.end - s.start,
                        "words": _synthetic_words(text, s.start, s.end),
                        "words_approximate": True})
    return out


def transcript_via_whisper(url_or_file: str,
                           model_name: str | None = None) -> list[dict] | None:
    """Last resort: download audio (yt-dlp) or read the local file, then
    transcribe locally with faster-whisper — free, no captions needed.
    Model: `model_name` or config.WHISPER_MODEL (base = High Accuracy
    default, tiny = Ultra-Fast)."""
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
        model = WhisperModel(model_name or config.WHISPER_MODEL,
                             device="cpu", compute_type="int8")
        segs = _whisper_segments(model, src)
        return segs or None
    except Exception as e:
        logger.warning("whisper transcription failed: %s", e)
        return None


def get_transcript(url_or_file: str,
                   whisper_model: str | None = None) -> dict | None:
    """Full fallback chain. Returns {text, segments, method} or None.
    `whisper_model` selects the local Whisper model size used by the
    last-resort whisper step (splitter speed/accuracy selector)."""
    vid = youtube_id(url_or_file)
    if vid:
        for name, fn in (("transcript-api", lambda: transcript_via_api(vid)),
                         ("yt-dlp-subs", lambda: transcript_via_ytdlp(url_or_file))):
            segs = fn()
            if segs:
                logger.info("Transcript via %s (%d segments)", name, len(segs))
                return {"text": _segments_to_text(segs), "segments": segs,
                        "method": name}
    segs = transcript_via_whisper(url_or_file, model_name=whisper_model)
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
