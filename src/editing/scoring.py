"""scoring.py — virality scoring for scene candidates (pure heuristics).

Adopted from the VIRALCUT AI specification (Phase 5 merge): every
candidate window is scored 0–100 across 7 heuristic dimensions —
hook strength, emotional intensity, semantic value, narrative
progression, conversational dynamics, retention/duration fit and
shareability — with an explainable per-dimension breakdown and a
one-line rationale. NO LLM call: transcript text features only
(question openers, numbers, superlatives, punctuation energy), plus
audio energy when the caller supplies per-window RMS values, plus
duration fit against the 10/15/20/30-second targets.

Dedup rule (VIRALCUT Stage 4): a candidate overlapping a higher-scored
candidate by more than 35% (of the shorter window) is dropped.
"""
from __future__ import annotations

import re

DIMENSIONS = ("hook_strength", "emotional_intensity", "semantic_value",
              "narrative_progression", "conversational_dynamics",
              "retention_fit", "shareability")

WEIGHTS = {"hook_strength": 0.22, "emotional_intensity": 0.14,
           "semantic_value": 0.16, "narrative_progression": 0.12,
           "conversational_dynamics": 0.10, "retention_fit": 0.14,
           "shareability": 0.12}

TARGET_DURATIONS = (10.0, 15.0, 20.0, 30.0)
DEDUP_OVERLAP = 0.35

_HOOK_WORDS = ("how", "why", "what", "secret", "never", "stop", "truth",
               "mistake", "watch", "nobody", "everyone", "first", "free",
               "biggest", "worst", "best")
_EMOTION_WORDS = ("amazing", "incredible", "crazy", "shocking", "love",
                  "hate", "wow", "unbelievable", "insane", "beautiful",
                  "terrible", "excited", "angry", "happy", "sad", "funny",
                  "hilarious", "scared", "surprised", "omg", "oh my god")
_VALUE_WORDS = ("because", "reason", "step", "tip", "learn", "means",
                "example", "fact", "study", "research", "percent", "%",
                "how to", "way to", "mistake", "rule", "key", "important")
_PROGRESSION_WORDS = ("then", "finally", "so", "until", "result",
                      "therefore", "after", "before", "next", "turns out")
_DIALOGUE_WORDS = ("said", "asked", "told", "replied", "answered",
                   "says", "asks")
_LAUGH_WORDS = ("haha", "hahaha", "lol", "laugh", "laughing", "funny",
                "joke", "punchline")
_SUPERLATIVES = ("best", "worst", "biggest", "greatest", "first", "never",
                 "always", "nobody", "everyone", "only", "secret",
                 "truth", "ever")
_CONNECTORS = ("and", "but", "so", "then", "or", "well", "now")
_STOPWORDS = set("the a an and or but of to in on for with is are was "
                 "were it its this that these those i you he she we they "
                 "be been being have has had do does did will would can "
                 "could should at by from as".split())


def _get(cand, key, default=None):
    if isinstance(cand, dict):
        return cand.get(key, default)
    return getattr(cand, key, default)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]


def _window_text(segments: list[dict], start: float, end: float) -> str:
    parts = []
    for s in segments or []:
        s_start = float(s.get("start", 0))
        s_end = s_start + float(s.get("duration", 0))
        if s_end > start and s_start < end:
            parts.append(s.get("text", ""))
    return " ".join(parts).strip()


def _window_energy_ratio(segments: list[dict], start: float, end: float,
                         energies: list[dict] | None) -> float:
    """Audio-energy ratio for the window (1.0 = average). When no RMS
    data is supplied, fall back to speech density (words/sec) relative
    to the whole transcript — the picker's long-standing energy proxy."""
    if energies:
        vals = [float(e.get("rms", 0)) for e in energies
                if float(e.get("end", 0)) > start
                and float(e.get("start", 0)) < end]
        all_vals = [float(e.get("rms", 0)) for e in energies]
        if vals and all_vals and sum(all_vals) > 0:
            return (sum(vals) / len(vals)) / (sum(all_vals) / len(all_vals))
    total_words = sum(len(s.get("text", "").split()) for s in segments or [])
    total_dur = sum(float(s.get("duration", 0)) for s in segments or [])
    if not total_words or total_dur <= 0:
        return 1.0
    avg_density = total_words / total_dur
    win_words = len(_window_text(segments, start, end).split())
    win_dur = max(end - start, 0.1)
    return (win_words / win_dur) / avg_density if avg_density else 1.0


def score_window(text: str, duration: float,
                 energy_ratio: float = 1.0) -> dict:
    """Score one candidate window. Returns {"total", "breakdown",
    "rationale"} — total and each dimension in 0–100."""
    text = (text or "").strip()
    low = text.lower()
    words = low.split()
    n_words = len(words)
    sentences = _sentences(text)
    first = sentences[0] if sentences else ""
    first_low = first.lower()
    first_words = first_low.split()
    wps = n_words / duration if duration > 0 else 0.0
    flags: list[tuple[str, str]] = []   # (dimension, phrase)

    # -- Hook strength ---------------------------------------------------
    hook = 15.0
    if "?" in first:
        hook += 30
        flags.append(("hook_strength", "question opener"))
    if any(w in first_low for w in _HOOK_WORDS):
        hook += 25
        flags.append(("hook_strength", "hook word in the opener"))
    if re.search(r"\d", first):
        hook += 15
        flags.append(("hook_strength", "number in the opener"))
    if 0 < len(first_words) <= 8:
        hook += 10
    if first_words and first_words[0] in ("stop", "never", "watch",
                                          "listen", "look"):
        hook += 10
        flags.append(("hook_strength", "imperative opener"))

    # -- Emotional intensity ----------------------------------------------
    excl = text.count("!")
    caps = sum(1 for w in text.split() if len(w) > 2 and w.isupper())
    emo_hits = sum(1 for w in _EMOTION_WORDS if w in low)
    energy_part = max(0.0, min(1.0, (energy_ratio - 0.7) / 0.6)) * 20
    emotion = (10 + min(25, 9 * excl) + min(20, caps * 6)
               + min(25, emo_hits * 8) + energy_part)
    if excl:
        flags.append(("emotional_intensity", "exclamatory delivery"))
    if emo_hits:
        flags.append(("emotional_intensity", "emotional language"))
    if energy_ratio >= 1.25:
        flags.append(("emotional_intensity", "high speech energy"))

    # -- Semantic value -----------------------------------------------------
    numbers = len(re.findall(r"\d", text))
    value_hits = sum(1 for w in _VALUE_WORDS if w in low)
    density_part = 25.0 if 1.8 <= wps <= 3.4 else (12.0 if wps >= 1.2 else 4.0)
    content_ratio = (sum(1 for w in words if w not in _STOPWORDS)
                     / n_words) if n_words else 0.0
    semantic = (min(25, 8 * numbers) + min(30, value_hits * 7)
                + density_part + content_ratio * 20)
    if numbers:
        flags.append(("semantic_value", "concrete numbers/facts"))
    if value_hits:
        flags.append(("semantic_value", "actionable or explanatory content"))

    # -- Narrative progression ----------------------------------------------
    narrative = 5.0
    if text.rstrip().endswith((".", "!", "?")):
        narrative += 35
        flags.append(("narrative_progression", "complete payoff ending"))
    if first_words and first_words[0] not in _CONNECTORS:
        narrative += 20
    prog_hits = sum(1 for w in _PROGRESSION_WORDS if w in low)
    narrative += min(25, prog_hits * 8)
    if len(sentences) >= 2:
        narrative += 15
        flags.append(("narrative_progression", "self-contained mini-story"))

    # -- Conversational dynamics ----------------------------------------------
    questions = text.count("?")
    you_hits = sum(1 for w in (" you ", " your ", " you're ") if w in
                   " " + low + " ")
    dial_hits = sum(1 for w in _DIALOGUE_WORDS if w in low)
    laugh_hits = sum(1 for w in _LAUGH_WORDS if w in low)
    conversation = (min(35, 15 * questions) + min(25, you_hits * 6)
                    + min(20, dial_hits * 8) + (20 if laugh_hits else 0))
    if questions:
        flags.append(("conversational_dynamics", "question & answer energy"))
    if laugh_hits:
        flags.append(("conversational_dynamics", "humour / punchline"))
    if you_hits:
        flags.append(("conversational_dynamics", "speaks directly to the viewer"))

    # -- Retention / duration fit ----------------------------------------------
    if duration > 0:
        rel = min(abs(duration - t) / t for t in TARGET_DURATIONS)
        retention = max(0.0, 100.0 - rel * 170.0)
        nearest = min(TARGET_DURATIONS, key=lambda t: abs(duration - t))
        if rel <= 0.25:
            flags.append(("retention_fit", f"fits the ~{int(nearest)}s format"))
    else:
        retention = 0.0
    if wps < 1.2:
        retention *= 0.6          # dead air hurts retention

    # -- Shareability ------------------------------------------------------------
    sup_hits = sum(1 for w in _SUPERLATIVES if w in low)
    quotable = any(4 <= len(s.split()) <= 10 for s in sentences)
    share = (min(30, sup_hits * 10) + (25 if quotable else 0)
             + min(25, sum(1 for w in ("secret", "nobody tells", "truth")
                           if w in low) * 12)
             + (20 if you_hits else 0))
    if quotable:
        flags.append(("shareability", "quotable one-liner"))
    if sup_hits:
        flags.append(("shareability", "bold superlative claim"))

    breakdown = {
        "hook_strength": round(min(100.0, hook), 1),
        "emotional_intensity": round(min(100.0, emotion), 1),
        "semantic_value": round(min(100.0, semantic), 1),
        "narrative_progression": round(min(100.0, narrative), 1),
        "conversational_dynamics": round(min(100.0, conversation), 1),
        "retention_fit": round(min(100.0, retention), 1),
        "shareability": round(min(100.0, share), 1),
    }
    total = round(sum(breakdown[d] * WEIGHTS[d] for d in DIMENSIONS), 1)

    top_dims = sorted(breakdown, key=lambda d: -breakdown[d])[:2]
    picked = [phrase for dim, phrase in flags if dim in top_dims][:3]
    if not picked:
        picked = [phrase for _, phrase in flags][:2]
    rationale = (" · ".join(picked) if picked
                 else "Steady segment — no standout viral markers")
    return {"total": total, "breakdown": breakdown, "rationale": rationale}


def _overlap_ratio(a_start: float, a_end: float,
                   b_start: float, b_end: float) -> float:
    overlap = max(0.0, min(a_end, b_end) - max(a_start, b_start))
    shorter = min(a_end - a_start, b_end - b_start)
    return overlap / shorter if shorter > 0 else 0.0


def dedup(ranked: list[dict],
          threshold: float = DEDUP_OVERLAP) -> list[dict]:
    """Drop candidates overlapping a higher-scored kept candidate by
    more than `threshold` of the shorter window (input must already
    be sorted by score, best first)."""
    kept: list[dict] = []
    for cand in ranked:
        if any(_overlap_ratio(cand["start_sec"], cand["end_sec"],
                              k["start_sec"], k["end_sec"]) > threshold
               for k in kept):
            continue
        kept.append(cand)
    return kept


def rank_candidates(candidates: list, segments: list[dict],
                    energies: list[dict] | None = None,
                    max_clips: int | None = None) -> list[dict]:
    """Score, sort (best first) and dedup scene candidates.

    candidates: dicts or objects with start_sec / end_sec (and
    optionally hook). segments: transcript segments [{text, start,
    duration}]. energies: optional per-window RMS data
    [{start, end, rms}] — speech density is used when absent.
    Returns enriched dicts: {start_sec, end_sec, hook, score,
    breakdown, rationale}."""
    scored = []
    for cand in candidates or []:
        start = float(_get(cand, "start_sec", 0))
        end = float(_get(cand, "end_sec", start))
        text = _window_text(segments, start, end)
        ratio = _window_energy_ratio(segments, start, end, energies)
        result = score_window(text, end - start, ratio)
        scored.append({
            "start_sec": round(start, 2), "end_sec": round(end, 2),
            "hook": _get(cand, "hook") or text[:90],
            "score": result["total"], "breakdown": result["breakdown"],
            "rationale": result["rationale"],
        })
    scored.sort(key=lambda c: -c["score"])
    scored = dedup(scored)
    return scored[:max_clips] if max_clips else scored
