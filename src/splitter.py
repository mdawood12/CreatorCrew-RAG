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
HOOK_WORDS = ("how", "why", "secret", "never", "stop", "truth", "mistake",
              "first", "finally", "suddenly", "believe", "watch", "free")


def _score_segment(seg: dict, avg_len: float) -> float:
    text = seg.get("text", "").lower()
    score = 0.0
    score += sum(1.5 for w in HOOK_WORDS if w in text)
    score += 1.0 if "?" in text else 0.0
    score += 1.0 if "!" in text else 0.0
    words = len(text.split())
    score += min(words / max(avg_len, 1), 2.0)      # denser speech = energy
    return score


def propose_candidates(segments: list[dict], clip_len: int = 30,
                       max_clips: int = 3) -> list[ClipCandidate]:
    """Group transcript segments into ~clip_len windows and rank them."""
    if not segments:
        return []
    avg_len = sum(len(s.get("text", "").split()) for s in segments) / len(segments)
    windows: list[ClipCandidate] = []
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
        score = sum(_score_segment(s, avg_len) for s in group)
        windows.append((score, ClipCandidate(
            start_sec=round(start, 2), end_sec=round(end, 2),
            hook=text.strip()[:90],
            reason=f"Heuristic score {score:.1f}: hook words, punctuation "
                   f"and speech density in this window")))
        i = max(j, i + 1)
    windows.sort(key=lambda w: -w[0])
    return [w[1] for w in windows[:max_clips]]


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
    dur = clip.duration
    if reframe == "crop":
        vf = "scale=-2:1920,crop=1080:1920,setsar=1"
    else:
        vf = ("split[a][b];"
              "[a]scale=1080:1920:force_original_aspect_ratio=increase,"
              "crop=1080:1920,gblur=sigma=40[bg];"
              "[b]scale=1080:-2[fg];"
              "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1")
    vf += ",eq=contrast=1.05:saturation=1.12:brightness=0.01,unsharp=5:5:0.6"
    if clip.hook:
        # Word-wrap the hook to at most 2 lines of ~30 chars so long hooks
        # never run off the 1080px-wide frame.
        words, lines = clip.hook.split(), []
        for w in words:
            if lines and len(lines[-1]) + len(w) + 1 <= 30:
                lines[-1] += " " + w
            elif len(lines) < 2:
                lines.append(w)
            else:
                lines[-1] = lines[-1].rstrip("…") + "…"
                break
        for i, line in enumerate(lines[:2]):
            vf += (f",drawtext=fontfile={FONT}:text='{_esc(line)}':"
                   "fontsize=42:fontcolor=white:borderw=3:bordercolor=black:"
                   f"x=(w-text_w)/2:y={70 + i * 58}:box=1:"
                   "boxcolor=black@0.45:boxborderw=12")
    vf += f",drawbox=x=0:y=ih-12:w='iw*t/{dur:.2f}':h=12:color=red@0.9:t=fill"
    cmd = ["ffmpeg", "-y", "-ss", str(clip.start_sec), "-t", str(dur),
           "-i", str(source), "-vf", vf,
           "-af", "loudnorm=I=-14:TP=-1:LRA=11",
           "-c:v", "libx264", "-preset", "medium", "-crf", "19",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
           str(out_path)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        raise RuntimeError("FFmpeg render failed: " + r.stderr[-800:])
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

    results = []
    for idx, clip in enumerate(candidates, 1):
        out = config.SHORTS_DIR / f"clip-{idx:02d}.mp4"
        render_clip(local, clip, out, reframe=reframe)
        meta = {**clip.model_dump(), "rights": rights,
                "source_note": source_note, "source": source,
                "transcript_method": tr["method"], "file": out.name}
        (config.SHORTS_DIR / f"clip-{idx:02d}.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8")
        memory.save_output("clip", source, "shorts",
                           {"file": out.name, "hook": clip.hook},
                           {"rights": rights})
        results.append(meta)
    return results
