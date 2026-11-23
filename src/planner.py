"""
planner.py — Transformation Planner [editorial editing plans].

Given a source clip the creator has DECLARED rights to, an LLM agent
produces a structured, 7-stage EDITORIAL editing plan (hook, audio
cleanup, trimming, format reframe, colour grade, voiceover/overlays,
final mix) as JSON that downstream tools can execute deterministically.

Safety by design [C1] — same rules as splitter.py:
- A rights declaration is MANDATORY (own / licensed / public-domain /
  creative-commons) plus a source note, validated here in code.
- The plan contains legitimate editorial transforms ONLY. It never
  includes obfuscation / fingerprint-alteration adjustments (no
  horizontal flip, no micro speed or filter tuning to alter
  recognition) and never promises evasion of copyright detection,
  claims or strikes. Editing does not transfer rights.

Demo Mode [C4]: with no API key, build_plan() returns a deterministic
template plan filled from the inputs instead of failing.
"""
from __future__ import annotations

import json
import re

from . import config
from .config import logger

# Same rights gate as splitter.py — keep these values in sync.
ALLOWED_RIGHTS = {"own", "licensed", "public-domain", "creative-commons"}

EXPECTED_STAGES = [
    "objective_and_hook",
    "audio_cleanup",
    "segment_trimming",
    "canvas_and_framing",
    "color_grade",
    "voiceover_and_overlays",
    "final_mix_and_export",
]

RISK_NOTE = (
    "Editing does not transfer rights: this plan applies only to "
    "content you have declared rights to use. Platform reused-content "
    "policies still apply — your original commentary and editorial "
    "value are what make the video yours, and no edit guarantees "
    "against copyright claims or strikes."
)

SYSTEM_PROMPT = """You are a Video Transformation & Editing Planning Agent inside a \
multi-agent content automation system.
Your goal is to convert a source clip — one the creator has declared \
rights to (own, licensed, public-domain or creative-commons) — into a \
structured EDITORIAL editing plan built on original commentary and \
genuine editorial value.

HARD RULES:
- Never include obfuscation or fingerprint-alteration adjustments: no \
horizontal flip for evasion, no micro speed tuning (e.g. 1.05x-1.35x) \
or micro filter shifts to alter platform recognition of the source.
- Never promise or imply evasion of copyright detection, claims, \
strikes or Reused Content policies. Editing does not transfer rights.
- Speed stays 1.0 by default. Any speed change must be an honest \
editorial pacing choice (e.g. a clearly labeled timelapse segment) \
and must carry a rationale.
- Colour work is an editorial look for clarity and mood, with a \
quality guardrail — never fingerprint-shift ranges.
- Follow the strict execution order below so downstream automation \
tools (FFmpeg, TTS/Voiceover, Subtitle generator, Renderer) can run \
deterministically.
- Output ONLY valid JSON matching the schema below. No markdown code \
fences, no extra commentary.

PIPELINE EXECUTION ORDER (MUST FOLLOW THIS SEQUENCE):
1. objective_and_hook: Define the viewer hook, the original \
commentary/educational angle, and why this clip is shown.
2. audio_cleanup: Mute or duck the original clip audio when commentary \
replaces it; strip third-party/background music; plan royalty-free \
BGM with a target level in dB.
3. segment_trimming: Break the source into focused segments instead of \
raw continuous playback; keep only relevant moments.
4. canvas_and_framing: Reframe the canvas for the target platform \
format (zoom_crop | split_screen | pip_with_backdrop), with a zoom \
scale and framing notes. NO horizontal flip.
5. color_grade: Editorial look adjustments for clarity and mood \
(plain-language adjustments, e.g. "gentle contrast lift"), with a \
quality guardrail so footage stays clear and natural.
6. voiceover_and_overlays: Sync the original voiceover, add captions, \
highlights and optional B-roll/callouts.
7. final_mix_and_export: Set speed_pacing (1.0 default; any change \
only as honest editorial pacing with rationale), balance voiceover vs \
BGM levels, and give the export profile.

OUTPUT JSON SCHEMA:
{
  "pipeline_version": "1.0",
  "rights": "<echo the declared rights value from the input>",
  "risk_note": "Editing does not transfer rights and platform \
reused-content rules still apply.",
  "steps": [
    {"order": 1, "stage": "objective_and_hook", "goal": "",
     "voiceover_script": "", "on_screen_hook": ""},
    {"order": 2, "stage": "audio_cleanup", "mute_original_audio": true,
     "original_audio_action": "mute | duck_to_10_percent | strip_music",
     "bgm_style": "", "bgm_target_db": -20},
    {"order": 3, "stage": "segment_trimming", "max_segment_seconds": 6,
     "cut_strategy": "", "keep_only_relevant_moments": true},
    {"order": 4, "stage": "canvas_and_framing",
     "canvas_mode": "zoom_crop | split_screen | pip_with_backdrop",
     "zoom_scale": 1.15, "framing_notes": ""},
    {"order": 5, "stage": "color_grade",
     "adjustments": {"contrast": "", "saturation": "",
                     "brightness": ""},
     "quality_guardrail": "Keep footage clear, legible, and free of \
heavy artifacts"},
    {"order": 6, "stage": "voiceover_and_overlays",
     "sync_voiceover": true, "captions_enabled": true,
     "caption_style": "", "overlays_or_broll": []},
    {"order": 7, "stage": "final_mix_and_export", "speed_pacing": 1.0,
     "speed_rationale": "", "voiceover_target_db": -3,
     "bgm_target_db": -22, "export_profile": "1080p_30fps_h264_aac"}
  ]
}"""


def _template_plan(metadata: dict, platform_format: str, niche: str,
                   creator_angle: str, rights: str,
                   preferences: dict | None) -> dict:
    """Deterministic Demo Mode plan [C4] — no LLM needed."""
    prefs = preferences or {}
    vertical = any(w in platform_format.lower()
                   for w in ("short", "reel", "9:16", "vertical", "tiktok"))
    angle = creator_angle.strip() or f"an original take on {niche}"
    return {
        "pipeline_version": "1.0",
        "rights": rights,
        "risk_note": RISK_NOTE,
        "steps": [
            {"order": 1, "stage": "objective_and_hook",
             "goal": f"Open with the creator's own angle: {angle}.",
             "voiceover_script": (creator_angle.strip()
                                  or f"Here is what most people miss about {niche}."),
             "on_screen_hook": (creator_angle.strip()[:60]
                                or f"The truth about {niche}")},
            {"order": 2, "stage": "audio_cleanup",
             "mute_original_audio": True,
             "original_audio_action": "strip_music",
             "bgm_style": "Royalty-free background music, low and neutral",
             "bgm_target_db": -20},
            {"order": 3, "stage": "segment_trimming",
             "max_segment_seconds": prefs.get("max_segment_seconds", 6),
             "cut_strategy": ("Keep only the moments that serve the "
                              "commentary angle; cut dead air and repeats."),
             "keep_only_relevant_moments": True},
            {"order": 4, "stage": "canvas_and_framing",
             "canvas_mode": "zoom_crop" if vertical else "pip_with_backdrop",
             "zoom_scale": 1.15,
             "framing_notes": (f"Reframe for {platform_format}; keep the "
                               "subject centred with safe margins for "
                               "captions.")},
            {"order": 5, "stage": "color_grade",
             "adjustments": {
                 "contrast": "gentle lift for clarity",
                 "saturation": "natural, true-to-life colour",
                 "brightness": "balanced for platform viewing"},
             "quality_guardrail": ("Keep footage clear, legible, and "
                                   "free of heavy artifacts")},
            {"order": 6, "stage": "voiceover_and_overlays",
             "sync_voiceover": True,
             "captions_enabled": True,
             "caption_style": "Short phrase captions, large and readable",
             "overlays_or_broll": ["Hook text in the first 3 seconds",
                                   "Callouts on key moments"]},
            {"order": 7, "stage": "final_mix_and_export",
             "speed_pacing": 1.0,
             "speed_rationale": ("Natural speed — the commentary carries "
                                  "the pacing."),
             "voiceover_target_db": -3,
             "bgm_target_db": -22,
             "export_profile": ("1080x1920_30fps_h264_aac" if vertical
                                else "1080p_30fps_h264_aac")},
        ],
    }


def _parse_plan(raw: str) -> dict:
    """Parse the LLM reply as JSON, with a brace-extraction repair."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("Planner did not return JSON.")
        return json.loads(text[start:end + 1])


def _validate(plan: dict, rights: str) -> dict:
    steps = plan.get("steps")
    if not isinstance(steps, list) or len(steps) != len(EXPECTED_STAGES):
        raise ValueError("Planner returned an invalid plan: "
                         "expected exactly 7 steps.")
    stages = [s.get("stage") for s in steps if isinstance(s, dict)]
    if stages != EXPECTED_STAGES:
        raise ValueError(f"Planner returned wrong stages: {stages}")
    plan["pipeline_version"] = "1.0"
    plan["rights"] = rights  # echo the validated declaration, not the LLM's
    if not str(plan.get("risk_note", "")).strip():
        plan["risk_note"] = RISK_NOTE
    return plan


def build_plan(metadata: dict, platform_format: str, niche: str,
               creator_angle: str, rights: str, source_note: str,
               preferences: dict | None = None) -> dict:
    """Build a 7-stage editorial transformation plan for a source clip.

    `rights` MUST be one of ALLOWED_RIGHTS and `source_note` is required
    [C1] — the same gate as splitter.split_video().
    """
    if rights not in ALLOWED_RIGHTS:
        raise ValueError(
            f"Rights declaration required — one of {sorted(ALLOWED_RIGHTS)}. "
            "The planner only works on content you have the rights to use.")
    if len(source_note.strip()) < 3:
        raise ValueError("A source note is required (your safety record).")

    if not config.KEY_MANAGER.has_keys:
        logger.info("Planner: no API key — returning Demo Mode template plan")
        return _template_plan(metadata, platform_format, niche,
                              creator_angle, rights, preferences)

    context = {
        "clip_metadata": metadata,
        "platform_and_format": platform_format,
        "niche_topic": niche,
        "creator_angle": creator_angle,
        "rights": rights,
        "source_note": source_note,
        "user_preferences": preferences or {},
    }
    prompt = (SYSTEM_PROMPT + "\n\nINPUT CONTEXT:\n"
              + json.dumps(context, indent=2))

    def _call(llm):
        return llm.invoke(prompt).content

    raw = config.call_llm_with_failover(_call)
    plan = _validate(_parse_plan(raw), rights)
    logger.info("Planner: 7-stage plan built for %s (%s)",
                platform_format, rights)
    return plan
