"""
splitter.py — Long-to-Short Viral Scene Splitter & Downloader [Phase 5].

Safety by design [C1]:
- A rights declaration is MANDATORY (own / licensed / public-domain /
  creative-commons). It is validated here in code — the UI cannot skip
  it — and saved into every clip's sidecar JSON.
- Transformations are legitimate editorial edits: clean trimming, 9:16
  reframe, burned captions, hook overlay, pacing, colour grade and
  loudness mastering. There are NO detection-evasion tricks.

Flow: source (URL or local file) -> transcript (fallback chain [C5])
-> candidate scenes (rules + optional LLM ranking) -> FFmpeg render
-> outputs/shorts/clip-XX.mp4 + clip-XX.json
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import config, memory, tools
from .config import logger
from .schemas import ClipCandidate

ALLOWED_RIGHTS = {"own", "licensed", "public-domain", "creative-commons"}
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def propose_candidates(segments: list[dict], clip_len: int = 30,
                       max_clips: int = 3) -> list[ClipCandidate]:
    """Group transcript segments into ~clip_len windows, then rank
    them with the 7-dimension virality scorer (src/editing/scoring.py,
    Phase 5): best first, near-duplicates (>35% overlap) dropped."""
    if not segments:
        return []
    from .editing import scoring
    windows: list[dict] = []
    i = 0
    while i < len(segments):
        start = segments[i]["start"]
        j = i
        while j < len(segments) and \
                (segments[j]["start"] + segments[j].get("duration", 3)) - start < clip_len:
            j += 1
        group = segments[i:max(j, i + 1)]
        end = group[-1]["start"] + group[-1].get("duration", 3)
        text = " ".join(s.get("text", "") for s in group)
        windows.append({"start_sec": round(start, 2),
                        "end_sec": round(end, 2),
                        "hook": text.strip()[:90]})
        i = max(j, i + 1)
    ranked = scoring.rank_candidates(windows, segments,
                                     max_clips=max_clips)
    return [ClipCandidate(
        start_sec=r["start_sec"], end_sec=r["end_sec"], hook=r["hook"],
        reason=f"Virality potential (heuristic) {r['score']:.0f}/100 "
               f"— {r['rationale']}")
        for r in ranked]


def _download(url: str, dest: Path) -> Path:
    subprocess.run(["yt-dlp", "-f", "bv*+ba/b", "-o", str(dest), url],
                   capture_output=True, timeout=1800, check=True)
    files = [p for p in dest.parent.glob(dest.stem + ".*")]
    if not files:
        raise RuntimeError("Download finished but no media file was found.")
    return files[0]


def _esc(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(":", "\\:")
            .replace("'", "\u2019").replace("%", "\\%"))


def render_clip(source: Path, clip: ClipCandidate, out_path: Path,
                reframe: str = "blur") -> Path:
    """Render one clip. Delegates to the modular editing pipeline
    (src/editing/) with the Minimal preset, which reproduces this
    splitter's original look exactly: blur/crop 9:16 reframe, the
    classic grade, hook overlay + progress bar, loudnorm -14 LUFS."""
    from .editing import pipeline, presets
    cfg = presets.build_config("Minimal")
    cfg["reframe"]["params"]["mode"] = reframe
    work = config.SHORTS_DIR / "_work" / f"pipe-{out_path.stem}"
    result = pipeline.render_segment(
        source, clip.start_sec, clip.end_sec, cfg, out_path, work,
        extras={"hook_text": clip.hook})
    for w in result["warnings"]:
        logger.warning("Splitter render: %s", w)
    return out_path


def split_video(source: str, rights: str, source_note: str,
                clip_len: int = 30, max_clips: int = 3,
                reframe: str = "blur") -> list[dict]:
    """Full pipeline. `rights` MUST be one of ALLOWED_RIGHTS [C1]."""
    if rights not in ALLOWED_RIGHTS:
        raise ValueError(
            f"Rights declaration required — one of {sorted(ALLOWED_RIGHTS)}. "
            "The splitter only processes content you have the rights to use.")
    if len(source_note.strip()) < 3:
        raise ValueError("A source note is required (your safety record).")

    work = config.SHORTS_DIR / "_work"
    work.mkdir(parents=True, exist_ok=True)
    if source.startswith("http"):
        local = _download(source, work / "source.mp4")
        transcript_source = source
    else:
        local = Path(source)
        if not local.exists():
            raise FileNotFoundError(f"Local file not found: {source}")
        transcript_source = source

    tr = tools.get_transcript(transcript_source)
    if not tr or not tr.get("segments"):
        raise RuntimeError("No transcript/timestamps could be produced for "
                           "this source, so viral scenes cannot be detected.")
    candidates = propose_candidates(tr["segments"], clip_len, max_clips)
    logger.info("Splitter: %d candidates from %s (transcript via %s)",
                len(candidates), source, tr["method"])
    from .editing import scoring as _scoring
    _ranked = _scoring.rank_candidates(
        [{"start_sec": c.start_sec, "end_sec": c.end_sec, "hook": c.hook}
         for c in candidates], tr["segments"])
    _score_by_span = {(r["start_sec"], r["end_sec"]): r for r in _ranked}

    results = []
    for idx, clip in enumerate(candidates, 1):
        out = config.SHORTS_DIR / f"clip-{idx:02d}.mp4"
        render_clip(local, clip, out, reframe=reframe)
        _sc = _score_by_span.get((clip.start_sec, clip.end_sec), {})
        meta = {**clip.model_dump(), "rights": rights,
                "source_note": source_note, "source": source,
                "transcript_method": tr["method"], "file": out.name,
                "word_timings": tools.word_timings_label(tr["segments"]),
                "virality_score": _sc.get("score"),
                "score_breakdown": _sc.get("breakdown"),
                "score_rationale": _sc.get("rationale")}
        (config.SHORTS_DIR / f"clip-{idx:02d}.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8")
        memory.save_output("clip", source, "shorts",
                           {"file": out.name, "hook": clip.hook},
                           {"rights": rights})
        results.append(meta)
    return results
