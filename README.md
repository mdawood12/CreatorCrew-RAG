# 🎬 CreatorCrew RAG — All-in-One Free Multi-Agent Content & Video Automation Studio

An **Agentic AI** studio for **YouTube and Facebook** creators, built with
**LangGraph multi-agents + RAG** and a **Streamlit** dashboard.
Give it a topic → get a Critic-audited YouTube + Facebook content package.
Paste a link → get a **100% original script** with a fresh angle.
Give it a long video you own → get **ready-to-post vertical clips**.

> **Cost: $0.** Every library is open source and the only API used is the
> **Google Gemini free tier** (no credit card). Your usage runs on **your
> own key and your own computer** — the author pays nothing for your usage,
> and you pay nothing at all.

---

## ✨ Features

| Module | What it does |
|---|---|
| **🤖 Multi-Agent Studio** | Planner → RAG Researcher → Scriptwriter → Critic (bounded self-critique loop, max 2 revisions) writes YouTube + Facebook packages as strict Pydantic objects |
| **📚 RAG Knowledge Base** | Real viral transcripts + official YouTube/Meta policy documents, chunked and stored in local **ChromaDB** with local embeddings — idempotent ingestion, metadata-filtered retrieval with citations |
| **🧠 Dual Memory** | Short-term: LangGraph checkpointer per session. Long-term: SQLite creator profile (niche, audience, tone) + full output history |
| **🔗 Link-to-Original Transformer** | Extracts ideas from a video/article link (transcript fallback chain: captions → yt-dlp subtitles → local Whisper) and writes an original script — originality is **measured** with an n-gram overlap check, not just claimed |
| **✂️ Viral Scene Splitter** | Detects highlight scenes in a long video and renders 9:16 clips with FFmpeg (reframe, grade, hook overlay, loudness master) + download buttons. **Rights declaration is mandatory** — only content you own / licensed / public-domain / CC |
| **🔑 API Key Resilience** | Key **pool** with health checks and automatic failover: if one free key hits its daily quota, the app switches keys by itself — work never stops |
| **📊 Evaluation** | LLM-as-a-Judge scoring (faithfulness, compliance, relevance) with optional RAGAS — report in the dashboard |
| **🆓 Demo Mode** | No key? The app still launches and shows sample outputs |

## 🏗️ Architecture

```
app.py (Streamlit — UI only, no business logic)
   │
src/
   ├── config.py       paths, settings, KeyManager (pool + failover), LLM factory
   ├── ingest.py       load → clean → chunk → embed (local) → ChromaDB (idempotent)
   ├── memory.py       SQLite long-term memory (profile + outputs)
   ├── schemas.py      Pydantic v2 contracts for every agent hand-off
   ├── tools.py        RAG retrieval (metadata filters) + transcript fallback chain
   ├── agents.py       LangGraph team: Planner/Researcher/Writer/Critic (loop ≤ 2)
   ├── transformer.py  link → ideas → original script (+ overlap audit)
   └── splitter.py     long video → viral candidates → FFmpeg clips (+ rights gate)
tests/
   ├── test_rag.py         smoke & relevance tests (no API key needed)
   └── evaluate_ragas.py   RAGAS (optional) + LLM-as-a-Judge evaluation
```

Design patterns: **Supervisor/Router**, **ReAct tool use**, **bounded
reflection/self-critique**, **dual-layer memory**, **strict data contracts**.

## 🚀 Quick Start (Windows, VS Code)

**Prerequisites:** Python 3.11/3.12 and FFmpeg
(`winget install Gyan.FFmpeg`, then reopen the terminal).

```bat
git clone <your-repo-url> CreatorCrew-RAG
cd CreatorCrew-RAG
python -m venv .venv
.venv\Scripts\activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` and add your **free** Gemini key from
[aistudio.google.com/apikey](https://aistudio.google.com/apikey)
(no card required). You can add several keys, comma-separated — the app
rotates them automatically.

**Add your data, build the knowledge base, test, run:**

```bat
:: put real transcripts / policy PDFs / CSVs into data\raw\
:: (optional) list viral video URLs in data\raw\viral_urls.txt
python -m src.ingest
pytest tests/test_rag.py
streamlit run app.py
```

Optional evaluation extras: `pip install -r requirements-eval.txt`
(the app and the LLM-as-a-Judge evaluation work without it).

## 🔐 Safety & honest limits

- **Your keys stay yours.** `.env` is git-ignored; keys are only ever
  shown masked. Never commit a real key — if one leaks, delete it in
  AI Studio and create a new one (1 minute).
- **Splitter rights gate.** The tool only processes videos you declare
  rights to, and the declaration is saved with every clip. Transformations
  are normal editorial edits — the tool contains **no** detection-evasion
  tricks, by design.
- **Free-tier limits are limits, not prices.** Gemini free quota is about
  1,500 requests/day per key; the key pool + backoff handles this.
- **Scale:** ChromaDB (local) is comfortable to ~100k chunks and SQLite
  suits a single creator. Both sit behind single modules, so upgrading to
  Postgres/pgvector later is a one-module change.
- **UI:** Streamlit is desktop-first and usable on mobile.

## 🎓 Academic note

Built as an **Agentic AI Module 2 Mid-Term Project**: RAG pipeline,
multi-agent orchestration with LangGraph, dual memory, structured
outputs, evaluation (RAGAS / LLM-as-a-Judge) and LangSmith observability
(opt-in via `LANGCHAIN_API_KEY`).

## 📄 License

MIT — free for anyone to use, learn from, and build on.
