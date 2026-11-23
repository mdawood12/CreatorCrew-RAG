# MASTER PROMPT — CreatorCrew Video Editing Upgrade (v1, FINAL)

**Role:** You are the senior engineer + architect upgrading the EXISTING
CreatorCrew RAG application (Streamlit + LangGraph + ChromaDB) into a modular
video editing studio. The existing app is the foundation — extend it, never
rebuild it, never break a working feature.

## 0. Hard constraints (non-negotiable)

1. **Zero cost, forever.** Only free/open-source components: FFmpeg,
   faster-whisper (local), Groq free tier, Gemini free tier, edge-tts
   (Microsoft Edge neural voices, free). No paid API, no card, no trial.
   If a feature cannot be free → drop it and report, never substitute paid.
2. **Preserve existing functionality.** Content Studio, Link Transformer,
   Viral Splitter, Transformation Planner, Evaluation & History, key pool,
   memory — all keep working exactly as before. Existing behaviour is the
   default until a user opts into a new option.
3. **Rights gate untouched.** Splitter/Planner process only declared-rights
   content (own / licensed / public-domain / creative-commons); the
   declaration stays mandatory and is saved with every output.
4. **Editorial transforms only.** All effects serve the viewer (framing,
   captions, pacing, clarity, music). No fingerprint-alteration defaults
   (no default flip, no micro speed/filter tuning to alter recognition).
5. **Cloud-compatible.** Must run on Streamlit Community Cloud free tier
   (ffmpeg via `packages.txt`; ~1 GB RAM working set; no background
   workers). Anything that cannot run there is out of scope, not faked.

## 1. Architecture strategy (modular by design)

**New package `src/editing/` — one module per operation, zero coupling:**

```
src/editing/
  registry.py     # single source of truth: every operation registers here
  pipeline.py     # runner: applies enabled ops in a fixed safe order
  presets.py      # 5 presets as plain config dicts (data, not code)
  trim.py         # silence trimming (silencedetect)
  framing.py      # ratios 9:16 / 1:1 / 16:9, zoom (zoompan), PiP, overlays
  grade.py        # color grade + brightness/contrast (editorial look)
  captions.py     # whisper word timings -> ASS burn-in, keyword emphasis
  audio.py        # BGM mix, sidechain ducking, voice clarity, loudnorm
  transitions.py  # xfade between segments
  analysis.py     # Groq transcription + Gemini video intelligence
  voices.py       # edge-tts voiceover generation
  export.py       # per-clip download + batch ZIP
```

**Rules that keep the rest of the app safe:**

- **Registry pattern.** Each operation is a pure function
  `(input_path, params) -> output_path` plus metadata (id, label, help,
  param schema, default, phase). The UI renders every toggle/slider FROM
  the registry — adding an option never requires UI surgery.
- **Fixed pipeline order.** trim → framing/zoom → grade → overlays →
  captions → audio mix → loudnorm → export. Order lives in ONE place
  (`pipeline.py`); operations never call each other directly.
- **Isolation.** Each op writes to its own temp file. If an op fails, it is
  skipped with a friendly one-line error and the render continues —
  one broken effect can never kill a whole render or another module.
- **Presets are data.** Professional / Cinematic / Social / Minimal /
  Custom are config dicts of op parameters. "Minimal" reproduces today's
  exact behaviour. User custom presets persist in the existing SQLite DB.
- **Splitter becomes a caller.** `splitter.py` keeps its public signature
  and delegates rendering to `pipeline.py`. Agents, transformer, planner,
  config and memory modules are NOT modified.
- **LLM only via `config.get_llm()` / `call_llm_with_failover()`** — the
  key pool and failover are reused, never duplicated.

## 2. Scope — Phase A (control & framing)

Registry + pipeline skeleton; presets & per-effect toggles/intensity in the
Splitter tab; ratios 1:1 and 16:9; silence trimming; zoom effects; PiP +
logo/text overlays; voice clarity filters (denoise/EQ); batch ZIP download.

**Definition of Done:** every op unit-tested on the rights-clean self-made
test video; ffprobe verifies dimensions/fps/duration per ratio; existing
splitter + planner behaviour regression-tested in Demo Mode; `py_compile`
clean; local git commit per phase.

## 3. Scope — Phase B (captions, audio, intelligence)

Captions burned from Whisper word timings (animated phrase style + keyword
emphasis); royalty-free BGM with sidechain ducking — stems rendered
separately, mixed, then loudnorm, verified with a per-second RMS scan
(never a single-graph mix); xfade transitions; Groq transcription as the
fast path with local Whisper fallback; **Gemini video intelligence** for
scene picking (≤5-min chunks, structured JSON scene/hook list, fallback to
the existing audio-energy picker on any failure); edge-tts voiceover
voices; translation option in the Link Transformer.

**Definition of Done:** end-to-end render on the test video with captions +
music verified by frame grabs and loudness (−14 LUFS ±1, true peak ≤ −1);
analysis fallback proven by a forced-failure run; honest phase report.

## 4. Explicitly parked (do NOT build)

Visual timeline editor · background job queue · 4K/60 fps export ·
face-detection reframing · paid voice providers (ElevenLabs/OpenAI) ·
custom non-Streamlit frontend.

## 5. UI/UX standard

Wizard flow everywhere (Import → Analyze → Edit → Export); controls
generated from the registry with plain-language labels + help text;
progress shown for every render; one-line friendly errors; Copy/Download
on every output; one accent colour, stat-card dashboard, theme via
`.streamlit/config.toml` + minimal CSS. Streamlit is desktop-first —
state this honestly in the README, never over-promise.

## 6. Working method

Phase by phase. Test each phase on real files before starting the next.
Commit locally per phase. After each phase report: **implemented /
partial / pending** — never claim an untested feature is done. Stop for
the owner's go between phases. Keep every change reversible: new code
lives in `src/editing/`; removing it must restore today's app untouched.
