# CreatorCrew RAG — Senior Architect Audit Report

**Date:** 2026-11-23 · **Type:** Read-only static audit (no code executed, no files modified)
**Scope:** Full application at `~/workspace/CreatorCrew-RAG/` — code, configuration, git history, plan documents (`README.md`, `UPGRADE-PLAN.md`, `MASTER-PROMPT-VIDEO-EDITING.md`)
**Method note:** A build of the new editing engine (`src/editing/`) is **in progress in the working tree** at audit time. Where the committed state (git HEAD) and the working tree differ, this report says so explicitly. "Production capability" = committed state (HEAD `e145a08`, 2026-11-21) plus what is actually deployed from it. Uncommitted work is audited at design-review level and marked **In development**.

---

## 1. Executive summary

CreatorCrew RAG is a single-user, zero-cost content-automation studio for one solo creator: a Streamlit UI over a LangGraph 4-agent team (Planner → Researcher → Scriptwriter → Critic), a ChromaDB RAG knowledge base of platform-policy documents, SQLite profile/history memory, and an FFmpeg-based video splitter — all powered exclusively by the Google Gemini **free tier** through a self-healing API-key pool. The committed application is genuinely functional and was verified end-to-end at build time (2026-11-19: 2,624 chunks ingested, test suite 6/6, a live agent run in 61.5 s with Critic verdict "pass", and a successful Streamlit Cloud deployment that is live today). A modular editing engine (registry + pipeline + presets + media library) is mid-build in the working tree and is well-architected, but it is uncommitted, and the repository of record is currently **not** the same thing as what runs in production (see §10). The system's hard limits are structural, not incidental: Streamlit Cloud's ephemeral storage and ~1 GB RAM, no background job queue, a single shared free-tier quota for all live-app visitors, and total dependence on one preview-class Gemini model. One test in the committed suite is stale and now fails (§6.1), and the compliance Critic fails *open* on LLM output errors (§6.2). Nothing in the system costs money today, and every planned capability has a credible free/open-source path (§9).

---

## 2. Purpose & business objectives

| Objective | How the code serves it |
|---|---|
| One studio for the owner's whole content workflow (scripts, repurposing, clips, editing plans) | 5 Streamlit tabs: Home, Content Studio, Link Transformer, Viral Splitter, Evaluation & History (`app.py`) |
| **Zero cost, permanently** — the owner has no bank card; any card-gated service is not merely undesirable but impossible | Only external API is Gemini free tier (`src/config.py` `KeyManager`); embeddings (`all-MiniLM-L6-v2`) and transcription (faster-whisper) run locally; hosting is Streamlit Community Cloud free tier; code storage is GitHub free |
| **Rights-gated by design** — the owner has previously lost a page to reused-content enforcement and requires the tooling to keep him safe | Rights declaration is enforced **in code**, not just UI, in `splitter.split_video()`, `planner.build_plan()` and `editing/intake.add_to_library()` (allowed values: `own`, `licensed`, `public-domain`, `creative-commons`; a source note ≥ 3 chars is mandatory); the declaration is persisted into every clip's sidecar JSON and the SQLite history |
| Originality must be *measured*, not asserted | 8-gram overlap audit (`agents.ngram_overlap`, limit 25 %) applied in the agent Critic and the Link Transformer (`transformer.py`) |
| Survive free-tier quota exhaustion without stopping work | Key pool with automatic failover on HTTP 429/403 (`config.call_llm_with_failover`, max 3 attempts, backoff) and a Demo Mode that keeps the whole app usable with no key at all |
| Originally built as a university Agentic-AI project; **re-purposed by the owner (2026-11-21) as his personal content automation studio** — a different project will be submitted for the mid-term | Reflected in the rewritten `README.md` (uncommitted) and `UPGRADE-PLAN.md` |

Non-goals, enforced in code and in `MASTER-PROMPT-VIDEO-EDITING.md` §0.4: no detection-evasion transforms (no default flip, no micro speed/filter fingerprint tuning), no platform watch-page downloader as a foundation (the new intake layer refuses watch-page hosts outright, `intake._WATCH_HOSTS`), no paid components.

---

## 3. Technology stack & architecture

### 3.1 Stack (from `requirements.txt`, ranges as pinned)

| Layer | Technology | Notes |
|---|---|---|
| UI | Streamlit `>=1.40,<1.52` | Single file `app.py` (608 lines); UI calls `src/` services only |
| Agent orchestration | LangGraph `>=0.4,<0.7`, LangChain `>=0.3.20,<0.4` | `StateGraph` + `MemorySaver` checkpointer (`agents.py`) |
| LLM | Gemini via `langchain-google-genai>=2.0,<3.0` | Default model `gemini-3-flash-preview` (`config.LLM_MODEL`, env-overridable); REST transport forced (gRPC hangs behind proxies — commit `393cd9d`) |
| Vector store | ChromaDB `>=0.5,<1.1` via `langchain-chroma` | Local persistent dir `data/chroma_db/`; collection `creatorcrew` |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` (local) | Free, offline after first download; pulls in CPU torch |
| Memory | SQLite (stdlib `sqlite3`) | `storage/creator_memory.db`; two tables (`creator_profile`, `outputs`) |
| Video | FFmpeg/ffprobe (system binary; `packages.txt` on cloud) | All rendering via `subprocess` |
| Transcription | faster-whisper `>=1.1,<2.0`, model `tiny`, CPU int8 | Plus `youtube-transcript-api` and `yt-dlp` subtitle stages ahead of it |
| Schemas | Pydantic v2 `>=2.9,<3.0` | `src/schemas.py` — every agent hand-off is a typed model |
| Evaluation | LLM-as-a-Judge built in; RAGAS isolated in optional `requirements-eval.txt` | `tests/evaluate_ragas.py`, `data/eval/eval_questions.json` (6 questions) |
| Observability | LangSmith, opt-in only when `LANGCHAIN_API_KEY` set | `config.py` [C3] |

Load-bearing pin: `av>=12,<16` — PyAV ≥ 19 removed an API faster-whisper needs; this pin is what keeps transcription working (commit `393cd9d`).

### 3.2 Module relationships

```
                         ┌────────────────────────────┐
                         │  app.py (Streamlit, 5 tabs)│
                         └─┬───────┬───────┬──────┬───┘
              ┌────────────┘       │       │      └───────────────┐
              ▼                    ▼       ▼                      ▼
        agents.py           transformer  splitter.py      tab: Evaluation
        (LangGraph)            │       │   │  (thin caller)   (reads outputs/)
              │                │       │   ▼                      ▲
              ├──── tools.py ──┘       │  editing/pipeline.py     │
              │     (retrieve,         │   │  registry order      │
              │      transcript        │   ▼                      │
              │      fallback chain)   │  editing/{trim,framing,  │
              ▼                        │   grade,captions,audio,  │
        ingest.py ──► ChromaDB         │   transitions,_util}     │
        (chunk/embed,                  │        ▲                 │
         content-hash ids)             │  editing/{intake,        │
              │                        │   presets,export}        │
              ▼                        ▼        │                 │
        config.py ◄──────────── every module ───┘                 │
        (paths, KeyManager pool, LLM factory, failover)           │
              │                                                   │
              ▼                                                   │
        memory.py (SQLite profile + outputs) ─────────────────────┘
        planner.py (7-stage plan; own module, uses config only)
```

### 3.3 Design patterns actually present in code (verified, not aspirational)

- **LLM factory + failover wrapper** — all LLM access flows through `config.get_llm()` / `config.call_llm_with_failover()`; no module constructs its own client.
- **Bounded reflection loop** — LangGraph conditional edge `critic → writer` capped by `MAX_REVISIONS = 2` (`config.py`, `agents._route_after_critic`).
- **Structured output with repair fallback** — `with_structured_output(ScriptPackage)` first, regex-extracted JSON + Pydantic re-validation second (`agents.writer_node`, `planner._parse_plan`).
- **Fallback chain for unreliable externals** — transcripts: API → yt-dlp subtitles → local Whisper (`tools.get_transcript`); policy fetch: trafilatura → raw urllib (`ingest._fetch_url`).
- **Idempotent ingestion** — chunk IDs are `sha256(source::text)[:24]`; re-ingest adds zero duplicates (`ingest.build_index`).
- **Registry pattern (in development)** — each editing operation is a pure function + metadata registered in `editing/registry.py`; the UI renders controls from the registry; the pipeline applies ops in one fixed stage order (`STAGE_ORDER = trim → framing → grade → overlays → captions → audio → loudnorm`) and **isolates failures**: a failed op is skipped with a warning, the render continues (`editing/pipeline.render_segment`).
- **Presets as data** — the five presets are plain dicts merged over registry defaults (`editing/presets.py`); `Minimal` reproduces the legacy splitter render.
- **Self-healing deployment** — `app.ensure_kb()` rebuilds an empty knowledge base on first run (built for Streamlit Cloud's ephemeral disk); `st.secrets` are mirrored into `os.environ` before `config` loads.

---

## 4. Complete project structure

```
CreatorCrew-RAG/
├── app.py                     Streamlit dashboard — 5 tabs, sidebar profile + key status (608 lines)
├── README.md                  User + deployment manual (rewritten version uncommitted)
├── UPGRADE-PLAN.md            Editing-upgrade plan, options map, competitor analysis (untracked)
├── MASTER-PROMPT-VIDEO-EDITING.md  Build spec for the editing engine (untracked)
├── packages.txt               "ffmpeg" — REQUIRED for Streamlit Cloud rendering (untracked in git!)
├── requirements.txt           Core deps, ranged pins (see §3.1)
├── requirements-eval.txt      Optional RAGAS only
├── .env.example               GOOGLE_API_KEYS pool + optional LangSmith
├── .gitignore                 Excludes .env, .venv, chroma_db, outputs mp4s, storage db, data/library
├── install-creatorcrew.bat    One-click Windows installer (untracked)
├── DEMO.html                  Static demo page from the 2026-11-19 delivery (untracked)
├── demo-agent-result.json     Captured live agent run (2026-11-19)
├── src/
│   ├── config.py              Paths, env, KeyManager pool + failover, LLM factory, validate()
│   ├── ingest.py              data/raw files + policy URLs + viral URLs → chunks → ChromaDB
│   ├── tools.py               RAG retrieval w/ metadata filters; transcript fallback chain
│   ├── agents.py              LangGraph team: planner/researcher/writer/critic + overlap audit
│   ├── schemas.py             Pydantic contracts: ScriptPackage, CriticReport, ClipCandidate, …
│   ├── memory.py              SQLite: creator_profile + outputs (only DB access point)
│   ├── transformer.py         Link → ideas → original script + measured overlap
│   ├── splitter.py            Rights gate, heuristic scene picking, render (now delegates to editing/)
│   ├── planner.py             Transformation Planner: 7-stage editorial plan JSON (committed e145a08)
│   └── editing/               ★ IN DEVELOPMENT (entire package uncommitted)
│       ├── __init__.py        Package contract docstring
│       ├── registry.py        Operation registry + fixed stage order
│       ├── pipeline.py        Segment extraction + isolated op runner + faststart export
│       ├── presets.py         Professional/Cinematic/Social/Minimal/Custom as data
│       ├── intake.py          Video input system + media library (ffprobe validation, watch-URL refusal)
│       ├── trim.py            Silence trimming (silencedetect)
│       ├── framing.py         reframe (3 ratios), zoom, PiP, text overlay, logo overlay, hook overlay
│       ├── grade.py           eq (contrast/saturation/brightness/gamma) + unsharp
│       ├── captions.py        faster-whisper word timings → ASS burn-in + keyword emphasis
│       ├── audio.py           voice_clarity, BGM sidechain-duck mix (separate stems), loudnorm
│       ├── transitions.py     xfade/acrossfade beat joins (max 4 parts)
│       ├── export.py          Batch ZIP of clips + sidecars
│       └── _util.py           run_ffmpeg, ffprobe wrapper, drawtext escaping, font path
├── tests/
│   ├── test_rag.py            6 pytest tests, no key needed (one is STALE — §6.1)
│   ├── test_editing_e2e.py    ★ IN DEVELOPMENT: full upload→render e2e incl. LUFS + RMS-scan checks
│   └── evaluate_ragas.py      RAGAS-or-LLM-judge evaluation → outputs/eval_report.json
├── data/
│   ├── raw/                   Owner-supplied dataset files — EMPTY in this tree (see §6.9)
│   ├── eval/eval_questions.json  6 policy questions with reference answers
│   ├── chroma_db/             Local vector store (32 MB on disk; gitignored)
│   └── library/               ★ Media library + index.json (gitignored; created by intake)
├── outputs/shorts/            Rendered clips + sidecar JSON (mp4s gitignored)
└── storage/                   creator_memory.db + app.log (gitignored)
```

---

## 5. Feature inventory & status matrix

Legend: **Functional** = committed and verified in use · **Partial** = works with material limits · **In development** = present in working tree, uncommitted, design-reviewed only (this audit ran no code) · **Missing** = not present.

### 5.1 Committed application

| # | Feature | Status | Evidence |
|---|---|---|---|
| 1 | Home dashboard (stat cards, key status, KB size) | Functional | `app.py`; live on Streamlit Cloud since 2026-11-20 |
| 2 | Content Studio tab (topic → YT+FB package) | Functional | `agents.run_content_studio`; live run verified 2026-11-19 (61.5 s, Critic pass, overlap 0.0 %) and on the live app 2026-11-21 ("Done — Critic-approved package") |
| 3 | Agent team (Planner/Researcher/Writer/Critic, ≤2 revisions) | Functional | `agents.py` graph; bounded loop in `_route_after_critic` |
| 4 | RAG ingest (files + policy URLs + viral URL transcripts) | Functional, content-thin | `ingest.py`; 2,624 chunks in the 2026-11-19 sandbox build — but `data/raw/` is empty and `viral_urls.txt` absent in this tree, so a fresh build ingests policy pages only (§6.9) |
| 5 | RAG retrieval with metadata filters + citations | Functional | `tools.retrieve` (`doc_type`/`platform` filters); Researcher pulls viral vs policy contexts separately |
| 6 | Long-term memory (profile + output history, SQLite) | Functional locally; **volatile on cloud** | `memory.py`; on Streamlit Cloud the DB is wiped on restart (§6.4) |
| 7 | Short-term memory (LangGraph MemorySaver) | Partial | In-process only; lost on restart; UI always uses `thread_id="default"` |
| 8 | Link Transformer + measured originality | Functional | `transformer.py`; overlap % surfaced in UI; over-limit results are *reported*, not blocked (warning logged) |
| 9 | Splitter — rights gate + source note | Functional | `splitter.split_video` raises `ValueError` on bad rights/short note (unit-verified 2026-11-19 with `rights='stolen'`) |
| 10 | Splitter — scene picking | Partial | Heuristic only: hook-word list + punctuation + speech density over transcript windows (`propose_candidates`). **No transcript → hard failure**; there is no audio-energy fallback despite plan documents referring to one (§6.8) |
| 11 | Splitter — render (9:16 reframe, grade, hook, loudnorm) | Functional | Committed monolithic FFmpeg render; verified output `outputs/shorts/clip-01.mp4` (29.6 s, 1080×1920). Working tree replaces it with pipeline delegation (§5.2) |
| 12 | Transformation Planner (7-stage JSON plan) | Functional | `planner.py` (committed `e145a08`); rights gate mirrors splitter; Demo-Mode deterministic template when no key; live + demo runs verified at build time |
| 13 | Key pool + health check + failover | Functional with caveats | `config.KeyManager`; failover unit-tested. Caveats: §6.3 |
| 14 | Demo Mode (no key) | Functional | Sample package in Studio; template plan in Planner; RAG/UI/splitter unaffected |
| 15 | Evaluation (LLM-judge / RAGAS) | Partial — built, never run | `tests/evaluate_ragas.py` exists; `outputs/eval_report.json` is **absent** in this tree, so the Evaluation tab shows instructions only; RAGAS never executed |
| 16 | LangSmith tracing | Functional (opt-in) | Off unless `LANGCHAIN_API_KEY` set |

### 5.2 Video input system (owner's spec A) — all In development (`editing/intake.py`, app.py Splitter tab rework)

| Item | Status | Evidence |
|---|---|---|
| Direct file uploads (MP4/MOV/MKV/WebM) | In development | `intake.ALLOWED_EXTS`; UI `st.file_uploader` + size pre-check vs `config.MAX_UPLOAD_MB = 500` |
| Authorized media URL import | In development | `intake.validate_media_url` — direct media-file URLs only; watch hosts (YouTube/Vimeo/TikTok/IG/FB/…) refused by design |
| Cloud storage integration | **Missing** | No Drive/Dropbox/S3 code anywhere; "cloud" today means the app's own local library + URL import |
| Previously uploaded video library | In development | `data/library/` + `index.json`; `add_to_library` / `list_library` / `get_library_item`; two e2e entries present on disk |
| Upload progress + file validation | Partial (in dev) | ffprobe validation with clear `ValueError`s (`validate_media_file`); progress is Streamlit's native upload bar + spinners — the URL downloader streams 1 MB chunks with a size cap but reports no percentage |

### 5.3 The 20 editing options (owner's master prompt) mapped against reality

| # | Option | Status | Where / note |
|---|---|---|---|
| 1 | Intelligent scene cutting | Partial | Heuristic transcript windows (`propose_candidates`); no visual/AI scene detection |
| 2 | Smart silence trimming | In development | `editing/trim.py` (silencedetect + padded keep-ranges) |
| 3 | Dynamic clip transitions | In development | `editing/transitions.py` (xfade, ≤4 beats) |
| 4 | Intelligent zoom effects | In development | `editing/framing.zoom` — fixed slow push-in; **not** subject-aware |
| 5 | Automatic video stabilization | **Missing** | No vidstab/deshake code anywhere |
| 6 | AI subtitle generation | In development | `editing/captions.py` (whisper word timings → ASS); transcript-level subtitles existed before via `tools.py` |
| 7 | Animated word captions | Partial (in dev) | Phrase-chunk captions; no per-word karaoke animation |
| 8 | Keyword emphasis | In development | Caption keyword param → bold + yellow in ASS |
| 9 | Professional caption templates | **Missing** | Exactly one hardcoded ASS style |
| 10 | Multilingual subtitle support | **Missing** as a feature | Transcript chain is English-pinned (`languages=["en"]`, `--sub-langs en.*`); Whisper auto-detect exists only implicitly; no caption translation |
| 11 | Smart vertical reframing | Functional | Committed 9:16 blur/crop; 1:1 + 16:9 added in dev (`framing.RATIOS`) |
| 12 | Cinematic color grading | Partial | `eq` + `unsharp` parameters and a "Cinematic" preset; no LUTs, no scene-adaptive grade |
| 13 | Brightness & contrast optimization | Functional | Grade op parameters (committed render already used fixed eq values) |
| 14 | Picture-in-picture layout | In development | `framing.pip` (corner + width %) |
| 15 | Custom graphics & overlays | In development | `framing.text_overlay`, `logo_overlay`, `hook` (text + progress bar) |
| 16 | Voice clarity enhancement | In development | `audio.voice_clarity` (highpass + `afftdn` + presence EQ) |
| 17 | Background music integration | In development | `audio.bgm_mix` (looped/faded bed from a user-supplied file; no bundled music library) |
| 18 | Automatic audio ducking | In development | Sidechain compressor in `bgm_mix`, stems rendered separately per the documented single-graph-collapse lesson |
| 19 | Sound effects integration | **Missing** | No SFX operation or asset library |
| 20 | Audio synchronization & normalization | Partial | Loudness normalization Functional (`loudnorm` −14 LUFS); no multi-track sync feature exists or is needed by the current workflows |

Supporting capabilities in development: 5 presets as data, per-op toggles/intensity rendered from the registry, **editable clip timestamps** in the UI (Step 3 number inputs), per-clip `st.video` preview + individual downloads, batch ZIP (`editing/export.make_zip`), progress callback per operation.

### 5.4 Planned intelligence features (Master Prompt Phase B)

| Feature | Status | Note |
|---|---|---|
| Groq transcription (fast path) | **Missing** | No `groq` dependency or code; local Whisper is the only ASR engine |
| Gemini video intelligence for scene picking | **Missing** | `src/editing/analysis.py` is specified in `MASTER-PROMPT-VIDEO-EDITING.md` §1 but the file does not exist |
| edge-tts voiceover voices | **Missing** | `src/editing/voices.py` likewise specified but absent; `edge-tts` not in requirements |
| Translation option in Link Transformer | **Missing** | Not implemented |
| Custom preset persistence in SQLite | **Missing** | Promised in the master prompt ("user custom presets persist"); no code — the UI's "Custom" is session-state only |
| Theme config / custom CSS (master prompt §5) | **Missing** | No `.streamlit/` directory exists |

---

## 6. Technical limitations, bugs & architectural weaknesses

### 6.1 ★ Stale test — committed suite is red
`tests/test_rag.py::test_config_validates` asserts `report["model"] == "gemini-2.5-flash"`, but `config.LLM_MODEL` defaults to `gemini-3-flash-preview` since commit `393cd9d` (2026-11-19). The test was not updated when the model changed, so the suite that was 6/6 at build time now fails on this assertion (unless `LLM_MODEL` is set in the environment). Any future "tests pass" claim must be re-verified after fixing this.

### 6.2 ★ Compliance Critic fails open
In `agents.critic_node`, if the Critic's structured-output call throws, the fallback returns `{"compliance_ok": True, "groundedness": 0.7, "verdict": "pass"}`. A malformed LLM response therefore **auto-passes the compliance gate** — the opposite of fail-safe for the one component whose job is policy safety. (The deterministic n-gram overlap check still runs and can force a revise, which limits but does not remove the risk.)

### 6.3 Key-pool weaknesses
- **Placeholder filter is string-specific:** `KeyManager.__init__` drops keys containing `"your-key"` only. The 2026-11-20 live incident — the owner's Streamlit Secret literally contained the placeholder `apni-key` — would **not** be filtered by this check; the pool reported a key present while every call failed.
- **Status chip is not a health check:** `KeyManager.status()` reports "active" if any key exists and none has been marked dead. `health_check()` exists but is never called by `app.py`; the sidebar can therefore show 🟢 while the key is invalid (observed in production, 2026-11-20).
- **Dead-key state is in-memory only** (`self.dead` set on a module-level singleton): every Streamlit Cloud restart/redeploy resets it, so failover re-learns failures on each cold start.
- **Error classification is substring matching** (`"429" in msg`, `"api key" in msg → 403`) in `call_llm_with_failover` — brittle against SDK error-format changes; non-matching errors abort immediately with no retry.

### 6.4 Streamlit Cloud platform limits (structural)
- **Ephemeral filesystem:** ChromaDB, the SQLite history/profile, the media library and rendered clips are all wiped on restart/redeploy. `ensure_kb()` rebuilds the KB (minutes-long spinner for the first visitor; the rebuild is also **non-deterministic** — a 2026-11-20 test rebuild produced 517 chunks vs 2,624 in the full build because a policy page fetch failed). History and library have **no** such rebuild — they simply vanish.
- **~1 GB RAM / shared CPU:** torch + sentence-transformers + Chroma + faster-whisper + FFmpeg encodes coexist in one process. The editing pipeline re-encodes at **every** operation (each op outputs CRF 20 `veryfast`), so an 8-op render of a 30 s clip is 8+ sequential lossy encodes — slow, and each `run_ffmpeg` call allows a timeout of 1,800 s (`editing/_util.FFMPEG_TIMEOUT`), far beyond what an interactive web session tolerates.
- **No background processing:** rendering runs synchronously inside the Streamlit script run. The progress bar in `app.py` is a callback over a blocking loop; a browser disconnect mid-render or a cloud timeout loses the work. There is no job queue, by platform design.
- **No authentication:** anyone with the live URL uses the owner's single key pool and sees the shared History (the README documents this sharing rule, but it remains an exposure: quota and privacy).

### 6.5 Single-model dependency
All LLM features depend on **one preview-class model**, `gemini-3-flash-preview`. Preview models can be renamed or withdrawn without notice — this has already happened once to this project (`gemini-2.5-flash` returned 404 "no longer available to new users" on 2026-11-19, commit `393cd9d`). Mitigation exists (`LLM_MODEL` env var) but requires a manual edit + redeploy by the owner.

### 6.6 Free-quota ceiling, shared by everyone
Gemini free tier ≈ 1,500 requests/day/key (README figure). One Content Studio run costs roughly 3–8 calls (planner, writer, critic, plus up to 2 revision cycles × writer+critic). The live app has **one** pool: all visitors draw from the same daily quota, so public sharing of the live link can exhaust the owner's own studio (observed failure mode "All API keys are down", 2026-11-20).

### 6.7 Whisper usage is inefficient and low-accuracy
- `tools.transcript_via_whisper` constructs a **new `WhisperModel("tiny")` on every call** (model reload per transcript). `editing/captions.py` does the opposite (module-level cached model) — the two halves of the codebase are inconsistent.
- The `tiny` model is the least accurate Whisper variant; for the owner's mixed English/Urdu speech and for caption quality this is the weakest link in the whole pipeline. Scene detection, captions and the Transformer all inherit its errors.
- **Repeated work in the UI:** the Splitter tab's "Detect scenes" re-transcribes the entire video on every click; transcripts are not cached per library item (in-dev code has the same behaviour).

### 6.8 Scene picking is heuristic-only, with a hard dependency
`propose_candidates` ranks transcript windows by a 13-word hook list, `?`/`!` presence and speech density. There is no visual analysis, no audio-energy analysis, and — despite `MASTER-PROMPT-VIDEO-EDITING.md` Phase B describing a "fallback to the existing audio-energy picker" — **no such picker exists**; if transcription fails, `split_video` raises and the workflow stops. Plan documents overstate the committed reality here; a supervisor should treat the documents as intent, not description.

### 6.9 Knowledge-base reproducibility gap
`data/raw/` is empty in this tree and `data/raw/viral_urls.txt` does not exist. Consequences: (a) a fresh `build_index()` ingests only the two `config.POLICY_URLS` pages — the "viral hooks" half of the RAG corpus is absent unless the owner re-supplies files; (b) the Researcher's `viral_transcript` retrieval silently degrades to whatever policy chunks exist; (c) doc-type classification of local files is a filename substring heuristic (`"polic" in name` → policy, else viral transcript), which will misclassify real datasets.

### 6.10 Portability bug — hardcoded Linux font path
`editing/_util.FONT` (and the now-dead `splitter.FONT`) hardcode `/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf`. On the owner's Windows PC — a primary deployment target — that path does not exist, so `drawtext`-based ops (hook, text overlay) and any font-dependent render will fail; the pipeline's isolation converts this into silently-missing overlays with a warning most users won't read. No per-OS font resolution or bundled font exists.

### 6.11 Two divergent video-acquisition paths
The committed `splitter._download()` runs `yt-dlp -f bv*+ba/b` against **any** http URL — including watch-page URLs — gated only by the rights declaration. The new `intake.py` deliberately refuses watch hosts and accepts only direct media files, and the reworked UI routes through intake. The old function remains publicly callable, so the codebase currently contains both the permissive and the strict policy. One of them should be retired (§11).

### 6.12 Media library (in dev) — small but real defects
- **No deduplication:** the on-disk `index.json` already contains the same source file twice (two `e2e-test` entries, 2026-11-23 07:18 and 07:19) — every test run and every re-add grows the library.
- **No delete/remove operation** in code or UI.
- **Absolute paths stored** in `index.json` (`/home/hatch/...`) — the index is meaningless on any other machine.
- **No locking** on the read-modify-write index update (acceptable for a single user; noted for completeness).

### 6.13 Dependency-range vs reality drift
`requirements.txt` pins LangChain <0.4 / LangGraph <0.7 / Chroma <1.1 / Streamlit <1.52. The owner's Windows machine actually runs **langchain 1.5.2, langgraph 1.2.23, chromadb 1.5.9, streamlit 1.67** (installed 2026-11-20 from unpinned step commands). The app demonstrably launched there, but the code has never been verified against those majors (e.g. LangGraph 1.x checkpointer imports, LangChain 1.x structured-output behaviour). There are effectively **two untested dependency realities**: the sandbox/cloud ranges and the owner's PC.

### 6.14 Smaller items
- `app.py` calls `config.os.getenv(...)` — works only because `config` imports `os`; fragile style.
- Registry-driven UI slider coercion `type(lo)(cur)` can truncate float params whose `min` is int-typed (and vice versa) — a latent parameter-rounding bug.
- Transformer returns over-limit-overlap scripts with only a log warning (by design — transparency over blocking — but a supervisor should note the 25 % limit is advisory there, enforced only in the agent loop).
- `ensure_kb()` runs inside the request path under `st.cache_resource`; simultaneous first visitors can race the Chroma build.
- Runtime artefacts (`outputs/` 15 MB, `.tmp/` test renders) accumulate without any cleanup policy; the editing pipeline's per-render work directories (`outputs/shorts/_work/…`) are never pruned.
- `data/library/` is gitignored (added in the uncommitted `.gitignore` change) — correct for media, but it also means the library feature is invisible to anyone cloning the repo.

---

## 7. Cost analysis

### 7.1 Current cost: $0 — and why (audited, not asserted)

| Component | Cost | Basis |
|---|---|---|
| Gemini LLM calls | $0 | Free tier via AI Studio keys; no billing account exists |
| Embeddings (MiniLM) | $0 | Local model, owner's CPU |
| Transcription (faster-whisper) | $0 | Local model, owner's CPU |
| Video rendering | $0 | FFmpeg (open source), local/cloud CPU |
| Vector store / DB | $0 | ChromaDB + SQLite, local files |
| Hosting | $0 | Streamlit Community Cloud free tier |
| Code storage | $0 | GitHub free (public repo) |
| Evaluation | $0 | LLM-judge uses the same free key; RAGAS is open source |

The binding constraint is therefore **not money but free-tier ceilings**: Gemini daily quota (§6.6), Streamlit Cloud RAM/CPU/session behaviour (§6.4), and the owner's own time and slow internet connection (measured as low as ~4 kB/s during the 2026-11-19 install — a 500 MB upload cap is theoretical for him; practical inputs are far smaller).

### 7.2 If scale were ever needed — cost triggers and the free alternative for each

| Trigger | Paid path (blocked for this owner — no card) | Free alternative already identified |
|---|---|---|
| Gemini quota exhausted daily | Paid Gemini tier | More free keys in the pool (implemented); Groq free tier for transcription/LLM tasks (planned) |
| Cloud RAM/timeouts on long renders | Paid host (Render/Railway class) | Render on the owner's PC (app already runs locally); keep cloud for scripts/plans only |
| Cloud storage wipes history/library | Paid persistent DB/storage | Treat GitHub as the permanent store (already the pattern for code); export history JSON |
| Voiceover quality beyond Piper/Edge | ElevenLabs etc. | edge-tts (free, planned `voices.py`); Gemini TTS free tier via the existing key |
| Faster transcription | Paid ASR APIs | Groq free-tier Whisper (planned `analysis.py`) |

---

## 8. Performance & scalability opportunities (concrete, code-tied)

1. **Cache the Whisper model in `tools.py`** the way `captions.py` already does — removes a full model load from every transcript call (single biggest easy win for Splitter/Transformer latency).
2. **Cache transcripts per library item** (store segments JSON beside the library index entry) — "Detect scenes" and re-renders stop re-transcribing the whole video.
3. **Upgrade the Whisper model size selectively** — `base` instead of `tiny` for captions/scene detection (still free, ~2–4× slower on CPU but materially better text); make it a config constant next to `EMBEDDING_MODEL`.
4. **Reduce pipeline re-encodes:** chain compatible video filters (`reframe`+`grade`+`hook` are all `-vf` ops) into one FFmpeg pass when they are adjacent in the stage order; keep isolation by falling back to per-op files on failure. Cuts render time and generational quality loss roughly in proportion to op count.
5. **Two-pass loudnorm with measured values** — current `loudnorm` is single-pass (linear-ish, less accurate); the production workflow the owner already uses elsewhere measures first. Cheap accuracy win in `audio.loudnorm`.
6. **Move KB build out of the request path** — pre-build and ship a seed `chroma_db` snapshot with the repo (or rebuild via a scheduled/local step), instead of `ensure_kb()`'s in-request multi-minute build with non-deterministic results.
7. **Cap concurrent heavy work in the UI** — disable render buttons while a render is running (session-state flag); today nothing prevents overlapping FFmpeg jobs in one session.
8. **Streamlit resource caching for the editing registry** — `load_operations()` is called on every Splitter-tab render; harmless now, worth a `cache_resource` if the registry grows.
9. **Scale ceiling (honest):** the architecture is single-user by design (SQLite, local files, in-process checkpointer). Multi-user scale would require Postgres/pgvector + a job queue + object storage — identified in the README as one-module swaps for DB/vector, but the *render queue* is the real missing piece and should not be attempted on Streamlit Cloud.

---

## 9. Free/open-source path for the planned AI repurposing + automated editing

The in-progress build already implements the majority of the *editing* half of the plan at zero cost, using only FFmpeg + faster-whisper: registry/pipeline/presets, three aspect ratios, silence trim, zoom, PiP, text/logo/hook overlays, grade, burned captions with keyword emphasis, voice clarity, BGM with sidechain ducking (stems-separate, per the documented audio lesson), xfade transitions, batch ZIP, and a validated media library with a rights gate. Its e2e test (`tests/test_editing_e2e.py`) is written to verify dimensions per ratio, loudness −14 LUFS ±1 and a per-second RMS no-collapse scan — the right acceptance criteria (this audit did not execute it; on-disk artefacts in `.tmp/editing-test/` show renders for all three ratios, captions and BGM were produced during the build).

What remains for full parity with the plan, all achievable free:

| Planned capability | Free route | Assessment |
|---|---|---|
| Fast transcription | **Groq free tier** (Whisper on LPU) as fast path, local Whisper fallback | Sound; mirrors the existing fallback-chain pattern in `tools.py`. Needs a `GROQ_API_KEY` slot in `KeyManager`-style config — do **not** hardcode a second ad-hoc key path |
| Video intelligence (scene/hook detection) | **Gemini multimodal** on ≤5-min chunks → structured JSON scene list; fall back to today's heuristic picker on any failure | Sound and uses the existing key pool + failover. This is the single highest-value remaining feature: it fixes §6.8. Must ship with the fallback *proven by a forced-failure test* (per master prompt DoD) |
| Voiceover voices | **edge-tts** (Microsoft Edge neural voices — the same Christopher/Jenny/Guy/Sonia set the competitor tool ships) | Free, no key; add `edge-tts` to requirements and a `voices.py` op that renders VO from the Planner's script and hands it to the existing ducking mix |
| Prompt-blueprint extraction (competitor's "Prompt Extractor") | Same Gemini-intelligence module: video → scene-by-scene breakdown + per-scene generation-prompt formula | Achievable with the analysis module; output is a reconstruction/formula, never the original prompt — label it that way in the UI |
| Translation in Transformer | Gemini prompt addition (existing key) or Whisper translate task | Trivial once analysis exists; keep the overlap audit applied to translated output too |
| Stabilization / caption templates / SFX | FFmpeg `vidstab` (two-pass) or `deshake`; ASS style presets as data; user-supplied SFX folder | All free; lower priority than intelligence features |

Explicitly **not** part of the free path (parked in the master prompt, correctly): visual timeline editor, background job queue, 4K/60 fps export, face-detection reframing, paid voice providers, custom non-Streamlit frontend.

---

## 10. Development status & outstanding tasks

### 10.1 Git history (5 commits, local `master` only — no remote refs in this clone)

| Commit | Date | Content |
|---|---|---|
| `2a1b208` | 2026-11-19 | v1: full studio (config/KeyManager, ingest, memory, schemas, agents, transformer, splitter, UI, tests) |
| `dd1868a` | 2026-11-19 | Verified build: deps installed, 2,624 chunks, pytest 6/6, live HTTP 200 |
| `393cd9d` | 2026-11-19 | Live-run fixes: `gemini-3-flash-preview` default, REST transport, hook word-wrap, `av<16` pin |
| `1ebbd05` | 2026-11-20 | Cloud-ready: secrets→env bridge, self-healing KB |
| `e145a08` | 2026-11-21 | Transformation Planner (HEAD) |

### 10.2 Working tree at audit time (uncommitted)

- **Modified:** `app.py` (Splitter tab rebuilt around intake + registry UI; +321/−… lines), `src/splitter.py` (render delegated to the editing pipeline; the old monolithic renderer deleted), `README.md` (full rewrite), `.gitignore` (+`data/library/`).
- **Untracked:** `src/editing/` (13 files, ~1,160 lines), `tests/test_editing_e2e.py`, `packages.txt`, `UPGRADE-PLAN.md`, `MASTER-PROMPT-VIDEO-EDITING.md`, `DEMO.html`, `install-creatorcrew.bat`.
- ⚠️ **`packages.txt` is untracked in this repo** while being the file the live cloud app depends on for FFmpeg. It exists on GitHub (owner uploaded it 2026-11-21, verified), but a clone of *this* repository would silently break cloud rendering. The local repo and GitHub are maintained by **manual file uploads**, so drift between them is a standing risk in both directions.

### 10.3 Outstanding tasks (from plan documents + this audit)

1. **Owner's pending GitHub upload** (one trip): the rewritten `README.md`, the new `app.py`, and `src/planner.py` — per `UPGRADE-PLAN.md` "Open loop". (The in-progress editing build will enlarge this list: all of `src/editing/`, the modified `splitter.py`, the e2e test.)
2. **Commit the in-progress build** locally in phase-sized commits (the master prompt's own working method requires per-phase commits; currently everything is one uncommitted lump, which defeats rollback).
3. **Fix the stale model assertion** (§6.1) and re-run the full suite + the new e2e test; record results.
4. **Live end-to-end Splitter test on the cloud app** post-`packages.txt` (the ffmpeg fix was deployed 2026-11-21; a full Create-clips run on the live app has not been evidenced since).
5. **Run the evaluation once** (`tests/evaluate_ragas.py`) so the Evaluation tab shows real scores; RAGAS optional.
6. **Supply a starter dataset** for `data/raw/` (or accept a policy-only KB) so fresh builds are reproducible (§6.9).
7. Phase B intelligence: `analysis.py` (Groq + Gemini) and `voices.py` (edge-tts) — not started (§5.4).

---

## 11. Recommended roadmap (prioritized)

**Phase 0 — Stabilize what exists (do first, all small):**
1. Fix `test_rag.py` model assertion; run `pytest` + `test_editing_e2e.py`; commit the editing build in two commits (Phase A ops, then Phase B ops) with the test results recorded. *Rationale: uncommitted, untested-in-suite code is the project's largest current risk.*
2. Add `packages.txt` (and the plan docs, installer, DEMO.html if wanted) to git; thereafter treat **git as the source of truth** and GitHub uploads as deployments of committed states only. *Rationale: eliminates repo↔GitHub drift (§10.2).*
3. Retire one acquisition path: make `splitter.split_video` refuse watch-page hosts the way `intake` does (or route it through `intake`). *Rationale: one rights policy, not two (§6.11).*
4. Make the Critic fail **closed** on structured-output errors (verdict `revise` with an explicit "critic unavailable" issue), or at minimum surface the fallback in the UI. *Rationale: §6.2 — the compliance gate must never silently pass.*

**Phase 1 — Intelligence (the owner's actual pain point):**
5. `editing/analysis.py`: Gemini video intelligence for scene picking with heuristic fallback + forced-failure test; Groq transcription fast path in `tools.py` with local fallback. *Rationale: converts scene detection from word heuristics to actual video understanding — the gap the owner identified on 2026-11-21 — at $0.*
6. Whisper fixes: shared cached model, `tiny`→`base` for captions, transcript caching per library item. *Rationale: §6.7, §8.1–8.3 — cheap, compounding wins.*

**Phase 2 — Voice & reach:**
7. `editing/voices.py` (edge-tts) wired to Planner scripts + the existing ducking mix; translation option in the Transformer. *Rationale: completes the repurposing loop (analyze → rewrite → voice → captions → export) free.*
8. Windows font resolution: bundle a DejaVu TTF in the repo and resolve the font path per-OS in `_util.py`. *Rationale: §6.10 — overlays currently fail silently on the owner's own PC.*

**Phase 3 — Hardening & housekeeping:**
9. Library dedupe + delete + relative paths; work-directory cleanup policy; KB seed snapshot for deterministic deploys; run evaluation and publish the report in-app.
10. Decide the owner's-PC dependency reality: either pin his venv to `requirements.txt` ranges or test against the installed 1.x majors and update the ranges. *Rationale: §6.13 — pick one truth.*
11. If the live link is shared beyond demos: add a secrets-based access passcode and a visible quota meter. *Rationale: §6.4/§6.6.*

**Explicitly deferred (keep parked):** timeline editor, job queue, 4K/60 fps, face-detect reframing, paid voices, custom frontend — each is either impossible on the free cloud tier or a complexity trap relative to a solo creator's return.

---

## 12. Risks & supervision notes

For the independent supervisor — the five things to watch, in order:

1. **Repo ≠ production.** Development happens in a local tree; GitHub (and therefore the live app) is updated by manual file uploads, and at audit time the local tree contains a large uncommitted build while GitHub contains at least one file (`packages.txt`) that local git does not track. Any review should start from `git status`, not from the live app's behaviour.
2. **The compliance gate can pass itself.** The Critic's exception fallback returns `verdict: "pass"` (§6.2), and the Transformer's 25 % overlap limit is advisory. The rights gates in code are genuinely enforced — but *output-side* originality/compliance assurance is weaker than the UI suggests.
3. **One preview model, one quota, no auth.** All intelligence depends on `gemini-3-flash-preview` and a shared free daily quota on a public URL (§6.5, §6.6, §6.4). Availability and cost shocks arrive without warning and without a paid fallback the owner could even buy (no bank card).
4. **Documents describe intent, not state.** `UPGRADE-PLAN.md` and the master prompt refer to capabilities that do not exist (audio-energy fallback picker, persisted custom presets, theme config, `analysis.py`, `voices.py`). This audit's status matrix (§5) is the corrected picture; insist future reports keep the implemented/partial/pending discipline the master prompt itself demands.
5. **Test discipline is slipping at exactly the wrong moment.** The one stale assertion (§6.1) means "tests pass" has not been true at HEAD since 2026-11-19, and the largest code change in the project's life (the editing engine) is currently uncommitted with its e2e test unrecorded. Require: green suite + e2e evidence *before* the GitHub upload, not after.

**Overall assessment:** a coherent, honestly-built single-user system whose architecture (factory + failover, bounded agents, registry-based editing, rights gates in code) is better than its operational discipline (version control, test freshness, deployment reproducibility). Closing that discipline gap is cheap and is the highest-leverage supervision goal for the next stage.

*— End of report. Static audit only; no code was executed or modified. The sole file created is this report.*
