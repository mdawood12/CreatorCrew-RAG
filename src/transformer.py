"""
transformer.py — Link-to-Original Content Transformer [Phase 5].

Input: a video or article URL.
Process: extract transcript/text + core ideas (never raw media re-uploads),
combine with RAG viral hooks + platform policy, generate an ORIGINAL
script with a fresh angle and commentary. The Critic's n-gram overlap
check [C13] runs on the result — originality is measured, not claimed.
"""
from __future__ import annotations

import json
import re

from . import config, memory, tools
from .agents import ngram_overlap, OVERLAP_LIMIT
from .config import logger
from .schemas import ScriptBeat, TransformResult


def extract_source(url: str) -> tuple[str, str]:
    """Return (source_text, kind) where kind is 'video' or 'article'."""
    if tools.youtube_id(url):
        tr = tools.get_transcript(url)
        if tr:
            return tr["text"], "video"
        raise RuntimeError("No transcript could be extracted from this video "
                           "(no captions and transcription failed).")
    text = tools.extract_article(url)
    if text:
        return text, "article"
    tr = tools.get_transcript(url)
    if tr:
        return tr["text"], "video"
    raise RuntimeError("Could not extract text from this URL.")


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


def _parse_beats(raw_beats) -> list[ScriptBeat]:
    """Defensively build ScriptBeat entries from raw LLM JSON.

    Skips non-object entries and any beat whose narration is empty or
    whitespace; coerces start_sec to a non-negative float (default 0.0)
    and defaults visual_prompt / on_screen_text to "".
    """
    beats: list[ScriptBeat] = []
    if not isinstance(raw_beats, list):
        return beats
    for entry in raw_beats:
        if not isinstance(entry, dict):
            continue
        narration = str(entry.get("narration") or "").strip()
        if not narration:
            continue
        try:
            start_sec = float(entry.get("start_sec") or 0.0)
        except (TypeError, ValueError):
            start_sec = 0.0
        beats.append(ScriptBeat(
            start_sec=max(0.0, start_sec),
            narration=narration,
            visual_prompt=str(entry.get("visual_prompt") or ""),
            on_screen_text=str(entry.get("on_screen_text") or "")))
    return beats


def transform_link(url: str) -> TransformResult:
    if config.get_llm() is None:
        raise RuntimeError("No API key configured (demo mode). "
                           "Add GOOGLE_API_KEYS to .env to use the Transformer.")
    source_text, _kind = extract_source(url)
    source_excerpt = source_text[:12000]

    hooks = tools.retrieve("viral hook structure retention", k=3,
                           doc_type="viral_transcript")
    hooks_ctx, _ = tools.format_context(hooks)
    policy = tools.retrieve("copyright reused content original commentary",
                            k=3, doc_type="platform_policy")
    policy_ctx, _ = tools.format_context(policy)

    prompt = (
        "You are a content transformer. From the SOURCE below, extract the "
        "core IDEAS only (facts, structure, topic) — never copy its wording.\n"
        "Then create a completely original script package with a FRESH angle "
        "and your own commentary, using the hook patterns and obeying the "
        "platform policy context. The script is a list of scene beats: one "
        "beat per scene, in chronological order, the first beat starting at "
        "0 seconds. Every narration line must be written entirely in your "
        "own words.\n"
        "Each beat's visual_prompt must be a complete, self-contained "
        "text-to-video generation prompt for that scene — subject, action, "
        "camera movement, lighting and visual style — detailed enough to "
        "paste straight into a video generator. on_screen_text is a short "
        "overlay line for that beat, or an empty string.\n"
        f"HOOK PATTERNS:\n{hooks_ctx}\n\nPOLICY:\n{policy_ctx}\n\n"
        f"SOURCE:\n{source_excerpt}\n\n"
        "Return ONLY valid JSON with keys: source_ideas (list of short "
        "strings), angle (string), cta (string — one short closing "
        "call-to-action line), beats (list of objects, each with "
        "start_sec (number, seconds from the start), narration (string), "
        "visual_prompt (string), on_screen_text (string)).")

    def _call(llm):
        return llm.invoke(prompt).content

    raw = config.call_llm_with_failover(_call)
    data = _extract_json(raw)
    if data is None:
        raise RuntimeError("Transformer: the model did not return JSON.")
    beats = _parse_beats(data.get("beats"))
    if not beats:
        raise RuntimeError("Transformer: the model returned no usable "
                           "beats — nothing was saved. Try again.")
    ideas = data.get("source_ideas", [])
    angle = data.get("angle", "")
    cta = str(data.get("cta") or "")
    script = " ".join(beat.narration for beat in beats)
    overlap = ngram_overlap(script, source_text)
    if overlap > OVERLAP_LIMIT:
        logger.warning("Transformer overlap %.2f%% above limit %.0f%% — "
                       "attempting one rewrite", overlap, OVERLAP_LIMIT)
        retry_prompt = (
            "The narration in the script package below is too close to "
            f"its source: measured word overlap is {overlap:.2f}% and "
            f"the limit is {OVERLAP_LIMIT:.0f}%. Rewrite EVERY beat's "
            "narration from scratch with genuinely different wording AND "
            "different sentence structure — rephrase completely, do not "
            "just swap synonyms. Keep the same ideas, angle and scenes; "
            "the visual prompts may stay aligned to the same scenes.\n\n"
            f"SOURCE (for reference only — do not copy its wording):\n"
            f"{source_excerpt}\n\nSCRIPT PACKAGE TO REWRITE:\n{raw}\n\n"
            "Return ONLY valid JSON with the SAME keys: source_ideas "
            "(list of short strings), angle (string), cta (string), "
            "beats (list of objects, each with start_sec, narration, "
            "visual_prompt, on_screen_text).")

        def _retry(llm):
            return llm.invoke(retry_prompt).content

        retry_data = _extract_json(config.call_llm_with_failover(_retry))
        if retry_data is not None:
            retry_beats = _parse_beats(retry_data.get("beats"))
            if retry_beats:
                retry_script = " ".join(b.narration for b in retry_beats)
                retry_overlap = ngram_overlap(retry_script, source_text)
                if retry_overlap < overlap:
                    beats, script, overlap = (retry_beats, retry_script,
                                              retry_overlap)
                    ideas = retry_data.get("source_ideas", ideas)
                    angle = retry_data.get("angle", angle)
                    cta = str(retry_data.get("cta") or cta)
    needs_review = overlap > OVERLAP_LIMIT
    if needs_review:
        logger.warning("Transformer overlap %.2f%% still above limit "
                       "%.0f%% after rewrite — flagging for human review",
                       overlap, OVERLAP_LIMIT)
    result = TransformResult(
        source_url=url,
        source_ideas=ideas,
        angle=angle,
        original_script=script,
        overlap_pct=overlap,
        needs_review=needs_review,
        beats=beats,
        cta=cta)
    memory.save_output("transform", url, "youtube+facebook",
                       result.model_dump(),
                       {"originality_overlap_pct": overlap})
    return result
