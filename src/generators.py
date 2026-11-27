"""
generators.py — Master Prompt generation [Step 2].

Two generators, both driven by the universal premium master prompt
(assets/premium_master_prompt.md) — the locked standard for every
template and every pack this module produces:

- generate_template_from_niche(niche): from ONLY a niche name, build
  a complete MasterPromptTemplate — recurring original characters,
  visual style, structure and posting defaults — ready to lock.
- generate_topic_pack(template, topic): from a LOCKED template and
  one topic, build the topic's full production pack (title, hook,
  timed beats with generation-ready visual prompts, CTA, caption,
  hashtags). The template is the law: characters, visual style and
  editing settings are rendered into the prompt verbatim and the
  model is forbidden from inventing new characters or changing any
  locked setting — only the topic changes from video to video.

format_production_pack() renders a pack as one clean markdown file
(the downloadable production pack). Pure — no Streamlit, no LLM.

The LLM seams mirror transformer.py exactly: a None-check on
config.get_llm(), one call through config.call_llm_with_failover,
and defensive extraction of the first JSON object in the reply.
"""
from __future__ import annotations

import json
import re

from . import config
from .config import logger
from .schemas import MasterPromptTemplate

PREMIUM_PROMPT_PATH = config.BASE_DIR / "assets" / "premium_master_prompt.md"

VALID_FORMATS = ("Shorts 30s", "Reel 60s", "YouTube 3–5 min")
VALID_LANGUAGES = ("English", "Urdu", "Roman Urdu")
# Target-format duration budgets in seconds (premium prompt §10 pacing
# contract: ~5s per scene, timeline within 5% of the target).
FORMAT_SECONDS = {"Shorts 30s": 30, "Reel 60s": 60, "YouTube 3–5 min": 240}


def load_premium_prompt() -> str:
    """The universal premium master prompt text — the standard."""
    try:
        return PREMIUM_PROMPT_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise RuntimeError(
            "The premium master prompt file is missing: "
            f"{PREMIUM_PROMPT_PATH}. It ships with the app in assets/ — "
            "restore it to use generation.")


def _extract_json(raw: str) -> dict | None:
    """Pull the first JSON object out of a model reply, or None."""
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _call_json(prompt: str) -> dict:
    """One LLM call through the failover seam; returns the JSON dict."""
    if config.get_llm() is None:
        raise RuntimeError("No API key configured (demo mode). "
                           "Add GOOGLE_API_KEYS to .env to use generation.")

    def _call(llm):
        return llm.invoke(prompt).content

    data = _extract_json(config.call_llm_with_failover(_call))
    if data is None:
        raise RuntimeError("Generator: the model did not return JSON.")
    return data


def _text(value) -> str:
    return str(value or "").strip()


def _clamp(value: str, valid: tuple[str, ...], default: str) -> str:
    return value if value in valid else default


def _beat_count(value, duration_sec: int) -> int:
    """Locked/auto beat count for a topic pack: the template's count
    when locked (> 0), else auto ≈ duration ÷ 5s per scene."""
    try:
        count = int(value or 0)
    except (TypeError, ValueError):
        count = 0
    return count if count > 0 else max(1, round(duration_sec / 5))


def generate_template_from_niche(niche: str) -> MasterPromptTemplate:
    """Build a complete, lockable template from ONLY a niche name.

    The premium master prompt is the standard; the model fills its
    slots for this niche. Values are validated through
    MasterPromptTemplate, with format/language clamped to the app's
    valid sets and the name defaulting to the niche itself.
    """
    niche = (niche or "").strip()
    if not niche:
        raise ValueError("Niche cannot be empty.")
    prompt = (
        f"{load_premium_prompt()}\n\n"
        "---\n"
        "TASK — create a complete, locked Master Prompt template for "
        f"ONE niche: {niche}\n\n"
        "Work as the Senior Multimedia Specialist of the standard "
        "above. This template is ZERO-TO-HERO: afterwards the creator "
        "will type ONLY a topic name, so leave NOTHING blank, thin or "
        "generic — every field complete, specific to this niche and "
        "ready to lock exactly as returned. The content it drives "
        "must carry real VALUE (a genuine fact, insight or story in "
        "every video — never empty hype) AND real ATTRACTION (a first "
        "frame and first line that stop the scroll). Build the "
        "storytelling for END RETENTION: the hook_style must open a "
        "loop in the first 3 seconds that only the payoff closes, "
        "with a midpoint renewal and a planted callback, so viewers "
        "stay to the last second; it must name the hook system (the "
        "Section 5 archetypes, scored 0–100, publish only at 60+). "
        "Invent 2–4 recurring ORIGINAL characters that fit this niche "
        "(never copy any existing channel's characters, names or "
        "branding — Section 11); each character's description must "
        "cover their look AND their role, in one or two sentences, "
        "precise enough to paste into a video generator so the "
        "character looks identical in every video. Choose the target "
        "format that fits this niche best. The CTA, tone, caption "
        "style and hashtags must be publishing-ready defaults, "
        "written exactly as Sections 5 and 9 require.\n\n"
        "Return ONLY valid JSON with keys: name (string — a clear "
        "template name), characters (list of objects with name and "
        "description), visual_style (string), target_format (one of "
        "\"Shorts 30s\", \"Reel 60s\", \"YouTube 3–5 min\"), beat_count "
        "(integer, 0 = auto), hook_style (string), cta (string), "
        "language (string), tone (string), caption_style (string), "
        "hashtags (string — the fixed hashtag set for the niche).")
    data = _call_json(prompt)

    characters = []
    raw_chars = data.get("characters")
    if isinstance(raw_chars, list):
        for entry in raw_chars:
            if not isinstance(entry, dict):
                continue
            cname = _text(entry.get("name"))
            if cname:
                characters.append({
                    "name": cname,
                    "description": _text(entry.get("description"))})
    try:
        beat_count = int(data.get("beat_count") or 0)
    except (TypeError, ValueError):
        beat_count = 0
    template = MasterPromptTemplate(
        name=_text(data.get("name")) or niche,
        characters=characters,
        visual_style=_text(data.get("visual_style")),
        target_format=_clamp(_text(data.get("target_format")),
                             VALID_FORMATS, "Reel 60s"),
        beat_count=max(0, min(30, beat_count)),
        hook_style=_text(data.get("hook_style")),
        cta=_text(data.get("cta")),
        language=_clamp(_text(data.get("language")),
                        VALID_LANGUAGES, "English"),
        tone=_text(data.get("tone")),
        caption_style=_text(data.get("caption_style")),
        hashtags=_text(data.get("hashtags")))
    logger.info("Generated master prompt template %r from niche %r "
                "(%d characters)", template.name, niche,
                len(template.characters))
    return template


def _parse_pack_beats(raw_beats) -> list[dict]:
    """Defensively build pack beats from raw LLM JSON.

    Skips non-object entries and any beat whose narration is empty;
    coerces start_sec / duration_sec to non-negative floats and
    defaults the string fields to "".
    """
    beats: list[dict] = []
    if not isinstance(raw_beats, list):
        return beats
    for entry in raw_beats:
        if not isinstance(entry, dict):
            continue
        narration = _text(entry.get("narration"))
        if not narration:
            continue

        def _num(key: str) -> float:
            try:
                return max(0.0, float(entry.get(key) or 0.0))
            except (TypeError, ValueError):
                return 0.0

        beats.append({
            "start_sec": _num("start_sec"),
            "duration_sec": _num("duration_sec"),
            "narration": narration,
            "visual_prompt": _text(entry.get("visual_prompt")),
            "on_screen_text": _text(entry.get("on_screen_text")),
            "music_cue": _text(entry.get("music_cue"))})
    return beats


def generate_topic_pack(template: MasterPromptTemplate,
                        topic: str) -> dict:
    """Generate one topic's full production pack from a LOCKED template.

    Only the topic is new. Every locked value — characters with their
    full descriptions, visual style, negative prompt, format, beat
    count, hook style, CTA, language, tone, caption style, hashtags —
    is rendered into the prompt verbatim, with a hard rule that the
    model must never invent characters or change locked settings.
    """
    topic = (topic or "").strip()
    if not topic:
        raise ValueError("Topic cannot be empty.")
    duration = FORMAT_SECONDS.get(template.target_format, 60)
    beat_count = _beat_count(template.beat_count, duration)
    if template.characters:
        characters_block = "\n".join(
            f"- {c.name} — {c.description}" for c in template.characters)
    else:
        characters_block = "(none — narrator only)"
    prompt = (
        f"{load_premium_prompt()}\n\n"
        "---\n"
        f"TASK — generate the complete production pack for ONE topic, "
        f"under the LOCKED master prompt template \"{template.name}\".\n\n"
        "LOCKED TEMPLATE VALUES (the law — already decided, never "
        "change them):\n"
        f"Characters:\n{characters_block}\n"
        f"Visual style: {template.visual_style}\n"
        f"Negative prompt (never show these): {template.negative_prompt}\n"
        f"Target format: {template.target_format} "
        f"(total duration budget ≈ {duration} seconds)\n"
        f"Beat count: {beat_count}\n"
        f"Hook style: {template.hook_style}\n"
        f"CTA (use this exact line): {template.cta}\n"
        f"Language: {template.language}\n"
        f"Tone: {template.tone}\n"
        f"Caption style: {template.caption_style}\n"
        f"Hashtags: {template.hashtags}\n\n"
        f"TOPIC (the only new thing): {topic}\n\n"
        "HARD RULE: use ONLY the locked characters and the locked "
        "visual style above. NEVER invent a new character, NEVER "
        "change the characters' looks, the style, the format or any "
        "editing/setting value. Every beat's visual_prompt must embed "
        "the full description of the character(s) appearing in that "
        "beat plus the locked visual style, must respect the negative "
        "prompt, and must be complete and self-contained — ready to "
        "paste into a video generator. Follow the standard: one idea, "
        "the 4-beat story system (Hook → Tension → Turn → Payoff), "
        "hook in the first 3 seconds, ~5 seconds per beat, the audio "
        "separation rule in the music cues, and the Section 9 caption "
        "format.\n\n"
        "Return ONLY valid JSON with keys: title (string), hook "
        "(string — the chosen opening hook line), beats (list of "
        "objects, each with start_sec (number), duration_sec "
        "(number), narration (string), visual_prompt (string), "
        "on_screen_text (string, may be empty), music_cue (string, "
        "may be empty)), cta (string), caption (string — the posting "
        "caption), hashtags (string), total_duration_sec (number).")
    data = _call_json(prompt)

    beats = _parse_pack_beats(data.get("beats"))
    if not beats:
        raise RuntimeError("Generator: the model returned no usable "
                           "beats — nothing was saved. Try again.")
    try:
        total = float(data.get("total_duration_sec") or 0.0)
    except (TypeError, ValueError):
        total = 0.0
    if total <= 0:
        total = round(max(b["start_sec"] + b["duration_sec"]
                          for b in beats), 1)
    pack = {
        "title": _text(data.get("title")) or topic,
        "hook": _text(data.get("hook")),
        "beats": beats,
        "cta": _text(data.get("cta")) or template.cta,
        "caption": _text(data.get("caption")),
        "hashtags": _text(data.get("hashtags")) or template.hashtags,
        "total_duration_sec": total,
    }
    logger.info("Generated pack %r for topic %r under template %r "
                "(%d beats, %.0fs)", pack["title"], topic,
                template.name, len(beats), total)
    return pack


def _mmss(seconds: float) -> str:
    total = int(round(float(seconds or 0)))
    return f"{total // 60}:{total % 60:02d}"


def format_production_pack(template: MasterPromptTemplate, topic: str,
                           pack: dict) -> str:
    """Render a generated pack as one clean markdown production pack."""
    beats = pack.get("beats") or []
    total = pack.get("total_duration_sec")
    if not total:
        total = (max((b.get("start_sec", 0) + b.get("duration_sec", 0)
                      for b in beats), default=0))
    lines = [
        f"# {pack.get('title') or topic}",
        "",
        f"**Template:** {template.name} · **Topic:** {topic}",
        f"**Format:** {template.target_format} · "
        f"**Total duration:** ~{_mmss(total)} ({float(total):.0f}s)",
    ]
    if pack.get("hook"):
        lines += ["", f"**Hook:** {pack['hook']}"]
    lines += ["", "## Beats"]
    for i, beat in enumerate(beats, start=1):
        start = float(beat.get("start_sec") or 0)
        end = start + float(beat.get("duration_sec") or 0)
        lines += ["", f"### Beat {i} · {_mmss(start)}–{_mmss(end)}",
                  "", beat.get("narration", "")]
        if beat.get("visual_prompt"):
            lines += ["", "**Visual prompt:**", "",
                      "```", beat["visual_prompt"], "```"]
        if beat.get("on_screen_text"):
            lines += ["", f"**On-screen text:** {beat['on_screen_text']}"]
        if beat.get("music_cue"):
            lines += ["", f"**Music cue:** {beat['music_cue']}"]
    if pack.get("cta"):
        lines += ["", "## CTA", "", pack["cta"]]
    if pack.get("caption"):
        lines += ["", "## Caption", "", pack["caption"]]
    if pack.get("hashtags"):
        lines += ["", "## Hashtags", "", pack["hashtags"]]
    lines.append("")
    return "\n".join(lines)
