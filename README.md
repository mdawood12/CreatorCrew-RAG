# 🎬 CreatorCrew RAG — Content Automation Studio

An **Agentic AI studio** for YouTube and Facebook creators, built with a
**LangGraph multi-agent team + RAG** behind a **Streamlit** dashboard.

Give it a **topic** → get a Critic-checked YouTube + Facebook content package.
Give it a **link** → get a fresh, original script with a new angle.
Give it a **long video you own** → get ready-to-post vertical clips + a full editing plan.

> **Cost: $0.** Every library is open source and the only API used is the
> **Google Gemini free tier** (no credit card, ever). You run it on **your own
> free key** — nobody pays anything.

**🔗 Live app:** https://creatorcrew-rag.streamlit.app
**💻 Code:** https://github.com/mdawood12/CreatorCrew-RAG

---

## ✨ What the studio does

| Module | What it does |
|---|---|
| **🏠 Home Dashboard** | Live stats at a glance — documents indexed (540+), scripts generated, clips rendered, API key status |
| **🤖 Content Studio** | A 4-agent team (Planner → RAG Researcher → Scriptwriter → Critic, max 2 revision rounds) writes a full YouTube + Facebook package from one topic |
| **📚 RAG Knowledge Base** | Real viral transcripts + official YouTube/Meta policy documents, chunked into local **ChromaDB** with local embeddings; answers come with citations |
| **🔗 Link Transformer** | Extracts the ideas from a video/article link (captions → yt-dlp subtitles → article text) and writes an **original** script — originality is *measured* with an n-gram overlap check (limit 25%), not just claimed |
| **✂️ Viral Splitter** | Turns a long video **you own** into ranked, ready-to-post 9:16 clips: scene detection, virality scoring, a full editing studio, loudness mastering and per-clip downloads |
| **🗂️ Transformation Planner** | Builds a deterministic 7-stage editorial editing plan (hook → audio cleanup → trimming → framing → color grade → voiceover/captions → final mix), stamped with your target duration and scene count |
| **📊 Evaluation & History** | LLM-as-a-Judge scoring + optional RAGAS; every output is saved in History |
| **🧠 Memory** | Your creator profile (niche, audience, tone) is saved once and used in every generation |
| **🔑 Key Resilience** | A **pool** of free Gemini keys with health checks and automatic failover — if one key hits its daily quota, the app switches by itself |
| **🆓 Demo Mode** | No key yet? The app still opens and shows sample outputs |

> **Rights first:** the Splitter and Planner only process videos you declare
> rights to (your own / licensed / public-domain / Creative Commons), and the
> declaration is saved with every clip. All transformations are normal
> editorial edits — the studio contains **no** detection-evasion tricks, by design.

---

## ✂️ The Viral Splitter in detail (6 steps)

1. **Rights declaration** — choose the rights basis and add a source note.
   Nothing is processed without it; the record is saved with every clip.
2. **Choose your video** — four sources:
   - **Upload a file** (MP4/MOV/MKV/WebM, max 500 MB)
   - **Direct media URL** (the link must point at a media file)
   - **My video URL (YouTube etc.)** — paste a watch-page link to **your own**
     video (YouTube, Vimeo, TikTok, Instagram, Facebook, Dailymotion, Twitch, X).
     It is fetched at up to 720p to save disk space, and the downloaded long
     video is **auto-deleted after rendering** (optional, on by default) —
     only your clips stay on disk.
   - **Media library** — reuse a video already stored by the app.
3. **Clip settings + scene detection** — a settings panel with two dropdowns:
   **Clip duration** (10s – 2 minutes, or your own Custom seconds) and
   **Number of clips** (1–10, or Custom). Speech engine: Tiny (fast) or
   **Base (default, more accurate)**. The app transcribes the video, groups
   scenes around your chosen length and ranks them by
   **Virality potential (heuristic)** — a 7-dimension score, shown with its
   full breakdown. Start/end timestamps and hook text stay editable.
4. **Style & editing studio** — 13 modular editing operations with presets:
   face-track reframing (per-shot crop that follows the largest face),
   trimming, captions (karaoke-style, Base-model word timings), color grade,
   transitions, audio cleanup and more. One failing option never breaks the rest.
5. **Render** — clips are rendered at **1080×1920**, loudness-mastered
   (~−14 LUFS), each with a download button and a sidecar JSON that carries
   the rights record.
6. **Transformation plan (optional)** — a 7-stage editorial plan for turning
   the clip into a commentary video, saved as JSON with your
   `target_duration_seconds` and `scene_count` from Step 3.

**Verified on real footage:** the full pipeline was tested end-to-end on a
real 6.5-minute, multi-speaker episode — transcription in ~30s, contextually
complete top clips, renders at 1080×1920 / −14 LUFS. The virality score is a
heuristic ranking aid, never a guarantee.

---

## 🚀 Run it on your PC (Windows)

### Step 1 — Install the two prerequisites
1. **Python 3.12 or newer** from [python.org](https://www.python.org/downloads/) (tick *"Add Python to PATH"* during setup).
2. **FFmpeg** — open Command Prompt and run:
   ```bat
   winget install Gyan.FFmpeg
   ```
   Close and reopen the terminal afterwards.

### Step 2 — Get the code
```bat
git clone https://github.com/mdawood12/CreatorCrew-RAG.git
cd CreatorCrew-RAG
```
(No Git? Download the ZIP from the GitHub page → *Code → Download ZIP* → extract.)

### Step 3 — Create the environment and install
```bat
python -m venv .venv
.venv\Scripts\activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```
⏳ The first install is the slow one (torch is large). Later runs are instant.
**Never delete the `.venv` folder** — it is your installed environment.

### Step 4 — Get your free Gemini API key (2 minutes, no card)
1. Open [aistudio.google.com/apikey](https://aistudio.google.com/apikey) and sign in with Google.
2. Click **Create API key** → copy the key.
3. In the project folder, copy `.env.example` and rename the copy to `.env`.
4. Open `.env` and paste your key like this:
   ```
   GOOGLE_API_KEYS=your-key-here
   ```
   💡 You can paste **several keys**, comma-separated — the app rotates them automatically when one runs out of daily quota.

### Step 5 — (Optional) Add your own knowledge
Put transcripts, policy PDFs or notes into `data\raw\` and run:
```bat
python -m src.ingest
```

### Step 6 — Run the studio
```bat
streamlit run app.py
```
Your browser opens at **http://localhost:8501**. Done 🎉

> 💡 **Tip:** the "My video URL" fetch works most reliably in the app running
> on your own PC — video sites sometimes block cloud-server IPs.

---

## 🖱️ Using the studio

### First time only — set your profile
In the left sidebar, open **Creator Settings**, fill in your **niche, target
audience and tone** → **Save**. Every script is now written in your style.

### Content Studio (your daily driver)
Type a topic → **Generate scripts** → read the **YouTube package** (hook,
script, CTA, SEO title, description, tags) and the **Facebook package**
(reel hook, pacing notes, caption). Download the package as JSON; it is also
saved in History automatically.

### Link Transformer
Paste a YouTube/article link → get a brand-new script built from the *ideas*,
with the originality overlap % shown — proof it is not a copy. Use this tab
for other creators' videos; the Splitter's URL option is only for your own.

### Viral Splitter
Follow the 6 steps above. Rights declaration first, always.

### Evaluation & History
Every script and clip you generate is listed here — reopen, copy or download
any past output.

---

## ☁️ Deploy it live (Streamlit Cloud, free)

1. Push this repo to **GitHub** (the repo must be **Public** — Streamlit's free deployer reads public repos).
2. Go to [share.streamlit.io](https://share.streamlit.io) → sign in with GitHub → **Create app → Deploy a public app from GitHub**.
3. Select: **Repository** `CreatorCrew-RAG`, **Branch** `main`, **Main file** `app.py`.
4. Open **Advanced settings**:
   - **Python version:** `3.12`
   - **Secrets:** paste your real key (⚠️ the *actual* key from your `.env` — never a placeholder):
     ```
     GOOGLE_API_KEYS = "your-real-key-here"
     ```
5. Click **Deploy**. First build takes a few minutes — the knowledge base builds itself automatically on first run.
6. Your app is live at `https://<your-app-name>.streamlit.app`.

**Two files that make the live app work — do not delete them:**
- `packages.txt` — contains `ffmpeg`, so the cloud server can render clips (without it, the Splitter fails with *"No such file or directory: 'ffmpeg'"*).
- `.env` is **never** committed — keys live only in your local file and the Streamlit Secrets box.

> **Sharing rule:** share the **GitHub link** freely (each person runs it with
> their own key). Keep the **live link** for demos — all visitors share your
> key's free daily quota and one shared History.

---

## 🏗️ Project structure

```
app.py                Streamlit UI (thin — no business logic)
video_settings.py     duration + scene-count selectors (Step 3 clip panel,
                      planning settings, pacing warnings) — pure + testable
src/
  config.py           settings, KeyManager (pool + failover), LLM factory
  ingest.py           load → chunk → embed (local) → ChromaDB (idempotent)
  memory.py           SQLite creator profile + output history
  schemas.py          Pydantic v2 contracts for agent hand-offs
  tools.py            RAG retrieval + transcript fallback chain
  agents.py           LangGraph team: Planner/Researcher/Writer/Critic
  transformer.py      link → ideas → original script (+ overlap audit)
  splitter.py         scene candidates + clip rendering (rights gate)
  planner.py          7-stage Transformation Planner (rights gate)
  editing/
    intake.py         uploads, direct URLs, own-video watch URLs (rights gate)
    scoring.py        7-dimension virality-potential ranking (heuristic)
    pipeline.py       modular editing operations runner
    framing.py        face-track reframing (per-shot, largest face)
    captions.py       karaoke captions from Whisper word timings
    trim.py / grade.py / transitions.py / audio.py / export.py
    presets.py        one-tap editing presets
tests/
  test_video_settings.py  duration/scene math + Step 3 clip presets
  test_watch_url.py       own-video URL intake (rights gate, auto-delete)
  test_viralcut.py        splitter scoring/render units
  test_phase0.py          foundation smoke tests
  test_editing_e2e.py     full editing pipeline on synthetic media
  test_rag.py             RAG smoke & relevance (no key needed)
  evaluate_ragas.py       optional RAGAS + LLM-as-a-Judge evaluation
packages.txt          cloud system package: ffmpeg
```

Design patterns: **Supervisor/Router**, **ReAct tool use**, **bounded
self-critique (≤ 2 revisions)**, **dual-layer memory**, **strict data contracts**.

## 🧪 Testing

```bat
.venv\Scripts\activate
python -m pytest tests/ -q
```
Pure functions are tested without Streamlit or a network connection; the
editing pipeline also has an end-to-end test, and the live UI is smoke-tested
after every deployment.

---

## 🛠️ Troubleshooting

| Problem | Fix |
|---|---|
| *"All API keys are down"* on the live app | Your Streamlit **Secrets** hold a wrong/placeholder key. Open *Manage app → Settings → Secrets*, paste the real key from your `.env`, **Save**, then *Reboot app* |
| *"No such file or directory: 'ffmpeg'"* (live Splitter) | `packages.txt` with the word `ffmpeg` is missing from the repo root — add it and let the app redeploy |
| *"Could not fetch this video from its URL"* | The site blocked the request — video sites often block cloud-server IPs. Run the app on your own PC for URL fetches |
| *Documents indexed: 0* on PC | Add files to `data\raw\` and run `python -m src.ingest` |
| Daily quota reached | Add another free key to `GOOGLE_API_KEYS` (comma-separated) — the app fails over automatically |
| A key leaked | Delete it in AI Studio and create a new one (1 minute). Never commit `.env` — it is git-ignored |

---

## 🔐 Honest limits

- **Free-tier limits are limits, not prices** — Gemini free quota is roughly 1,500 requests/day per key; the key pool + backoff handles it.
- **Scale:** local ChromaDB is comfortable to ~100k chunks; SQLite suits a single creator.
- **URL fetching** depends on the video site allowing the request; uploads and direct media URLs always work.
- **Virality potential is a heuristic** — it ranks scenes by measurable signals; it cannot promise views.
- **UI:** Streamlit is desktop-first and usable on mobile.

## 📄 License

MIT — free for anyone to use, learn from, and build on.
