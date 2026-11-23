# MASTER PROMPT — CreatorCrew FINAL UPGRADE (Consolidated, v1)

**Role:** Senior AI Software Architect + Engineer upgrading the EXISTING
CreatorCrew RAG application into a complete, modular **content automation
studio**. The existing app is the foundation — extend it, never rebuild it,
never break a working feature. This prompt consolidates, in proper order:
the owner's 20-option editing specification, the zero-cost Step-1 scope,
the UI/UX direction, the Ali Ai Studio competitive analysis, the Video
Input & Repurposing Module specification, and the 2026-11-23 audit fixes.

## 0. Hard constraints (non-negotiable)

1. **Zero cost, forever.** Only free/open-source: FFmpeg, faster-whisper
   (local), Groq free tier, Gemini free tier, edge-tts (free Edge neural
   voices). No paid API, no card, no trial. If a feature cannot be free →
   drop it and report it. Never substitute paid.
2. **Preserve existing functionality.** Content Studio, Link Transformer,
   Viral Splitter, Transformation Planner, Evaluation & History, key pool,
   memory — all keep working. Existing behaviour is the default until a
   user opts into a new option (the "Minimal" preset reproduces it).
3. **Authorized sources only.** The input system serves user-owned,
   licensed, public-domain and Creative-Commons media. Third-party video
   downloading is NOT a feature and never becomes the foundation.
   The existing rights gate stays mandatory; the declaration is saved
   with every output.
4. **Editorial transforms only.** Every effect serves the viewer
   (framing, captions, pacing, clarity, music). No fingerprint-alteration
   defaults (no default flip, no micro speed/filter recognition tuning).
5. **Cloud-compatible.** Must run on Streamlit Community Cloud free tier
   (FFmpeg via `packages.txt`; ~1 GB RAM working set; no background
   workers — progress-based processing, reported honestly as such).
6. **Version discipline.** Every phase ends in a local git commit.
   Nothing the live app needs may stay untracked (e.g. `packages.txt`).
   Plan documents must describe reality — implemented / partial / pending
   stated exactly, never overstated.

## 1. Architecture (modular, registry-driven)

New package `src/editing/` — one module per operation, zero coupling:

```
src/editing/
  registry.py    # single source of truth for every editing operation
  pipeline.py    # runner: fixed order, per-op isolation + temp files
  presets.py     # 5 presets as data dicts (not code)
  intake.py      # uploads, authorized URL import, media library
  trim.py        # silence trimming (silencedetect)
  framing.py     # ratios 9:16/1:1/16:9, zoom (zoompan), PiP, overlays
  grade.py       # colour grade + brightness/contrast (editorial look)
  captions.py    # whisper word timings -> ASS burn-in, keyword emphasis
  audio.py       # BGM + sidechain ducking, voice clarity, loudnorm
  transitions.py # xfade between segments
  analysis.py    # Groq transcription + Gemini video intelligence
  voices.py      # edge-tts voiceover generation
  blueprint.py   # Prompt Blueprint: video -> scene-by-scene prompt formula
  export.py      # per-clip download + batch ZIP
```

- **Registry pattern:** each operation is a pure function
  `(input_path, params) -> output_path` + metadata (id, label, help,
  param schema, default, phase). The UI renders all toggles/sliders FROM
  the registry — adding an option never requires UI surgery.
- **Fixed pipeline order:** trim → framing/zoom → grade → overlays →
  captions → audio mix → loudnorm → export. Defined once in `pipeline.py`;
  operations never call each other.
- **Isolation:** a failing operation is skipped with a friendly one-line
  error; the render continues. One broken effect never kills a render
  or another module.
- **Splitter becomes a caller** of the pipeline (public signature kept).
  `agents.py`, `transformer.py`, `planner.py`, `config.py`, `memory.py`
  are not modified except where a phase explicitly says so.
- **LLM only via `config.get_llm()` / `call_llm_with_failover()`** —
  the key pool is reused, never duplicated.

## 2. Phase 0 — Audit fixes (do first; small, high-trust)

From AUDIT-REPORT-2026-11-23.md:
1. Fix the stale test asserting the old model name — test suite must be
   green and truthful again.
2. **Critic must fail CLOSED on compliance:** if the Critic's structured
   output cannot be parsed, the package is marked "needs review",
   never silently `compliance_ok: True / verdict: pass`.
3. **Real key health check in the UI:** the sidebar status must call
   `health_check()` (cached, cheap) — "Key active" may only be shown
   for a key that actually answered. Placeholder filter must reject
   obvious placeholders generally, not one literal string.
4. Commit everything the live app depends on (incl. `packages.txt`);
   correct the plan documents to match reality.
**DoD:** pytest green; a forced-bad-Critic test proves fail-closed; UI
status verified against a deliberately wrong key; clean git status.

## 3. Phase 1 — Video Input System + Editing Engine A

**Input (intake.py):** direct file upload; authorized direct-media URL
import (watch-page URLs stay refused); previously-uploaded **media
library** (`data/library/` + JSON index: name, source, rights, note,
duration, size, date) reusable as splitter input; ffprobe validation
(mp4/mov/mkv/webm, 500 MB cap, codec/duration probe) with clear errors.

**Repurposing:** scene candidates from the existing picker; **editable
start/end timestamps per clip** before rendering; auto clip-duration
detection; ratios **9:16, 1:1, 16:9**.

**Editing ops (registry):** presets (Professional / Cinematic / Social /
Minimal / Custom) + per-op toggles & intensity; silence trimming; zoom
effects; PiP + logo/text overlays; colour grade + brightness/contrast;
voice clarity (denoise/EQ); hook overlay; loudnorm. **Preview** per
rendered clip (`st.video`) + individual downloads + **batch ZIP**.

**DoD:** end-to-end on the rights-clean test video (upload → library →
candidates → edit timestamps → preset render → preview → ZIP); ffprobe
verifies every ratio; regression: all other tabs run in Demo Mode;
commit.

## 4. Phase 2 — Captions & Audio

Animated phrase captions burned from Whisper word timings (ASS) with
**keyword emphasis** styling; royalty-free **BGM with sidechain ducking**
— stems rendered separately, mixed, loudnormed, and verified with a
per-second RMS scan (never a single-graph mix); **xfade transitions**.

**DoD:** frame grabs prove captions/emphasis; loudness −14 LUFS ±1,
true peak ≤ −1; RMS scan shows no collapse; commit.

## 5. Phase 3 — Intelligence (the Ali Ai Studio lessons, done safely)

- **Groq transcription** as the fast path (free key, word-level),
  local Whisper fallback on any failure.
- **Gemini video intelligence** in `analysis.py`: the model WATCHES the
  video (≤5-min chunks, auto-partitioned) → structured JSON of scenes,
  retention hooks and suggested clips — upgrading scene picking beyond
  audio-energy; fallback to the existing picker on any failure.
- **Prompt Blueprint** (`blueprint.py`): for a rights-declared clip
  ≤120 s, produce a scene-by-scene breakdown + generation-prompt
  formula (subject, action, camera, lighting, style) — an honest
  reconstruction for learning and original production, labelled as such.
- **Voices** (`voices.py`): edge-tts built-in voices (Christopher,
  Jenny, Guy, Sonia + more) for voiceover generation; check whether the
  owner's existing Gemini key can power Gemini TTS on the free tier —
  adopt only if verified free.
- **Translation** option in the Link Transformer (Gemini, free tier).

**DoD:** each feature proven on the test video with its fallback
force-tested; no feature ships on a claim; commit per feature.

## 6. Phase 4 — UI/UX & Project Library

Wizard flow everywhere (Import → Analyze → Edit → Export); Home becomes
a **project library** (cards with status: Draft / Ready, search, filter)
backed by the existing SQLite history; one accent colour, stat cards,
theme via `.streamlit/config.toml` + minimal CSS; plain-language labels
+ help text; progress on every render; Copy/Download on every output.
Streamlit is desktop-first — state it honestly, never over-promise a
custom desktop UI.

**DoD:** a first-time user completes upload → clip → download without
instructions; README updated to the new reality; commit.

## 7. Explicitly parked (do NOT build)

Visual timeline editor · true background job queue · 4K/60 fps export ·
face-detection reframing · paid voice providers (ElevenLabs, OpenAI,
ai33) · platform video downloaders · custom non-Streamlit frontend.

## 8. Working method

Phase by phase, in the order above. Test on real files before moving
on. Local commit per phase. After each phase, report **implemented /
partial / pending** exactly. Stop for the owner's go between phases.
Every change reversible: removing `src/editing/` and the Phase-0 fixes
must restore the previously working app.

## 9. Phase 5 — VIRALCUT merge (2026-11-23, owner's Step 2)

The owner shared his friend's "VIRALCUT AI" master prompt (a separate
Windows desktop clipping app) and authorized implementing its
legitimate capabilities INTO CreatorCrew — one app, one GitHub push.
This section records exactly what was adopted and what was not. It
supersedes the §7 parked line "face-detection reframing" for the
smart-reframe item only; everything else in §7 stays parked.

**Adopted (implemented in the editing engine / splitter):**
- **Virality scoring** (`src/editing/scoring.py`) — every scene
  candidate scored 0–100 across the VIRALCUT 7 heuristic dimensions
  (hook strength, emotional intensity, semantic value, narrative
  progression, conversational dynamics, retention/duration fit,
  shareability) from transcript text features + speech-density/RMS
  energy + fit to 10/15/20/30 s targets. Pure heuristics, no LLM.
  Per-dimension breakdown + one-line rationale in the UI; candidates
  sorted by score; >35%-overlap dedup against higher-scored clips.
- **Face-track smart reframing** (reframe mode "smart") — frames
  sampled across the clip, face centre detected with OpenCV YuNet
  (free model in `assets/`, Haar cascade fallback), centre path
  smoothed with EMA + deadband damping, crop window computed from
  the smoothed path; no face → classic blur-pad fallback. The
  classic blur/crop modes are untouched.
- **Karaoke captions** (captions style "karaoke") — word-level ASS
  with the active word highlighted yellow as it is spoken; keyword
  words cyan. The default phrase style is unchanged.
- **Whisper robustness** (VIRALCUT Rule 2) — `word_timestamps=True`
  wrapped in try/except; on DTW/alignment failure the transcribe
  retries without word timestamps and synthesizes word timings by
  interpolating word lengths across each segment; word lists are
  filtered defensively, never subscripted blindly. Clean-audio
  behaviour unchanged.
- **Speed/accuracy + duration selectors** — Splitter tab: Whisper
  model selector (tiny = ⚡ Ultra-Fast default, base = 🎯 High
  Accuracy; `config.WHISPER_MODEL` / `WHISPER_MODEL` env) and
  target-duration quick-selects (~10/~15/~20/~30 s) feeding the
  existing scene picker.

**Deliberately NOT adopted:**
- **yt-dlp / platform downloading (YouTube/TikTok/etc.)** — the
  owner's own authorized-sources specification governs: the input
  system stays uploads + authorized direct-media URLs + media
  library behind the mandatory rights gate.
- **A separate Windows desktop app** (React/FastAPI/VIRALCUT) —
  the owner's one-app decision: everything lives in CreatorCrew's
  existing Streamlit app so there is a single GitHub push.
