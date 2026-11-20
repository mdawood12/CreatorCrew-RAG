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
from .schemas import TransformResult


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
        "Then create a completely original script with a FRESH angle and "
        "your own commentary, using the hook patterns and obeying the "
        "platform policy context.\n"
        f"HOOK PATTERNS:\n{hooks_ctx}\n\nPOLICY:\n{policy_ctx}\n\n"
        f"SOURCE:\n{source_excerpt}\n\n"
        "Return ONLY valid JSON with keys: source_ideas (list of short "
        "strings), angle (string), original_script (string, complete "
        "narration script in your own words).")

    def _call(llm):
        return llm.invoke(prompt).content

    raw = config.call_llm_with_failover(_call)
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise RuntimeError("Transformer: the model did not return JSON.")
    data = json.loads(m.group(0))
    script = data.get("original_script", "")
    overlap = ngram_overlap(script, source_text)
    if overlap > OVERLAP_LIMIT:
        logger.warning("Transformer overlap %.2f%% above limit %.0f%%",
                       overlap, OVERLAP_LIMIT)
    result = TransformResult(
        source_url=url,
        source_ideas=data.get("source_ideas", []),
        angle=data.get("angle", ""),
        original_script=script,
        overlap_pct=overlap)
    memory.save_output("transform", url, "youtube+facebook",
                       result.model_dump(),
                       {"originality_overlap_pct": overlap})
    return result
