"""captions.py — burned-in captions from faster-whisper word timings.

The clip's audio is transcribed locally (free; model from
config.WHISPER_MODEL — base High Accuracy by default since the
2026-11-23 verification showed tiny mis-hearing key vocabulary;
tiny remains selectable for speed), words are grouped into short
readable phrases (the Track-A
chunking rule: a punctuation break only counts once the chunk has
>= 3 words, so a lone word never flashes on screen), styled as ASS
and burned in with libass. Words from the user's keyword list are
emphasised (bold + colour). A "karaoke" style (Phase 5, adopted from
VIRALCUT AI) highlights each word in yellow at the moment it is
spoken; keyword words are cyan.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .. import config as _config
from . import registry
from ._util import probe, run_ffmpeg

_MODELS: dict[str, object] = {}


def _model():
    name = _config.WHISPER_MODEL
    if name not in _MODELS:
        from faster_whisper import WhisperModel
        _MODELS[name] = WhisperModel(name, device="cpu",
                                     compute_type="int8")
    return _MODELS[name]


def _words_for_clip(in_path: Path, workdir: Path) -> list[dict]:
    """Transcribe the clip file itself and return word timings.
    faster-whisper occasionally chokes on direct MP4 decode, so the
    audio is first extracted to a 16 kHz WAV (the proven route)."""
    wav = workdir / f"{in_path.stem}_audio16k.wav"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-i", str(in_path), "-vn", "-ac", "1", "-ar", "16000",
                    str(wav)], capture_output=True, timeout=600, check=True)
    segments, _info = _model().transcribe(str(wav), beam_size=1,
                                          word_timestamps=True)
    words = []
    for seg in segments:
        for w in (seg.words or []):
            text = w.word.strip()
            if text:
                words.append({"text": text, "start": w.start, "end": w.end})
    return words


def _chunks(words: list[dict], max_words: int = 7) -> list[dict]:
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        ends_sentence = w["text"].endswith((".", "!", "?"))
        if len(cur) >= max_words or (ends_sentence and len(cur) >= 3):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return [{"start": c[0]["start"], "end": c[-1]["end"],
             "words": [w["text"] for w in c], "word_objs": c}
            for c in chunks]


def _ass_time(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _build_ass(chunks: list[dict], keywords: set[str], font_size: int,
               play_w: int, play_h: int) -> str:
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_w}
PlayResY: {play_h}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,3,1,2,40,40,90,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for c in chunks:
        parts = []
        for w in c["words"]:
            clean = w.strip(".,!?;:\"'()[]").lower()
            if clean in keywords:
                parts.append(f"{{\\c&H00FFFF&\\b1}}{w}{{\\r}}")
            else:
                parts.append(w)
        text = " ".join(parts).replace("\n", " ")
        lines.append(f"Dialogue: 0,{_ass_time(c['start'])},{_ass_time(c['end'])},"
                     f"Default,,0,0,0,,{text}")
    return head + "\n".join(lines) + "\n"


# ASS colours are BGR: yellow = &H0000FFFF&, cyan = &H00FFFF00&.
_ACTIVE = "&H0000FFFF&"      # yellow — the word being spoken right now
_KEYWORD = "&H00FFFF00&"     # cyan — emphasis keywords when not active


def _build_ass_karaoke(chunks: list[dict], keywords: set[str],
                       font_size: int, play_w: int, play_h: int) -> str:
    """Karaoke captions: one Dialogue event per word, the active word
    highlighted yellow (bold) while the rest of the phrase stays on
    screen in white; keyword words are cyan when not active."""
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_w}
PlayResY: {play_h}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,3,1,2,40,40,90,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for c in chunks:
        objs = c.get("word_objs") or []
        for i, w in enumerate(objs):
            start = float(w["start"])
            end = float(w["end"])
            if i + 1 < len(objs):
                # Hold the phrase on screen until the next word is
                # spoken — otherwise every inter-word pause flashes
                # a brief no-caption gap (verification finding, 2026-11-23).
                end = max(end, float(objs[i + 1]["start"]))
                end = min(end, float(c["end"]))
            if end <= start:      # zero-length timing — borrow a beat
                nxt = (objs[i + 1]["start"] if i + 1 < len(objs)
                       else c["end"])
                end = max(float(nxt), start + 0.08)
            parts = []
            for j, ow in enumerate(objs):
                text = ow["text"]
                clean = text.strip(".,!?;:\"'()[]").lower()
                if j == i:
                    parts.append(f"{{\\b1\\c{_ACTIVE}}}{text}{{\\r}}")
                elif clean in keywords:
                    parts.append(f"{{\\c{_KEYWORD}}}{text}{{\\r}}")
                else:
                    parts.append(text)
            text = " ".join(parts).replace("\n", " ")
            lines.append(
                f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},"
                f"Default,,0,0,0,,{text}")
    return head + "\n".join(lines) + "\n"


def captions(in_path: Path, params: dict, ctx: dict) -> Path:
    words = _words_for_clip(in_path, ctx["workdir"])
    if not words:
        raise ValueError("No speech could be transcribed for captions.")
    keywords = {k.strip().lower() for k in
                (params.get("keywords") or "").replace(",", " ").split()
                if k.strip()}
    info = probe(in_path)
    ass_path = ctx["workdir"] / f"{in_path.stem}_captions.ass"
    chunks = _chunks(words)
    if params.get("style") == "karaoke":
        ass_text = _build_ass_karaoke(chunks, keywords,
                                      int(params["font_size"]),
                                      info["width"], info["height"])
    else:
        ass_text = _build_ass(chunks, keywords, int(params["font_size"]),
                              info["width"], info["height"])
    ass_path.write_text(ass_text, encoding="utf-8")
    out = ctx["workdir"] / f"{in_path.stem}_captions.mp4"
    run_ffmpeg(["-i", str(in_path), "-vf", f"ass={ass_path}",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "aac", "-b:a", "160k", str(out)])
    return out


registry.register(registry.Operation(
    id="captions", stage="captions", phase="B", label="Burned-in captions",
    help="Auto-captions from the clip's own speech, burned onto the video "
         "so silent viewers can follow along.",
    func=captions,
    params=[
        {"key": "style", "type": "select", "default": "default",
         "choices": ["default", "karaoke"], "label": "Caption style",
         "help": "Default shows short phrases; karaoke highlights "
                "each word in yellow as it is spoken."},
        {"key": "font_size", "type": "int", "default": 52, "min": 28,
         "max": 96, "step": 2, "label": "Caption size",
         "help": "Caption font size in pixels."},
        {"key": "keywords", "type": "text", "default": "",
         "label": "Emphasis keywords",
         "help": "Words to highlight in colour (comma separated). "
                "Filled from the editing panel."},
    ]))
