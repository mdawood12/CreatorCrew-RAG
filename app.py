"""
app.py — CreatorCrew RAG Streamlit dashboard.

Architect rules applied (master prompt v2, Section 7):
- Home dashboard first: stat cards + 3 big actions; a new user
  understands the app in 10 seconds.
- One wizard flow per tab: 1 Input -> 2 Settings -> 3 Run -> Result.
- Heavy objects (vector store) load ONCE via st.cache_resource.
- No business logic in this file — the UI only calls src/ services.
- Demo Mode [C4]: without an API key the app still runs and shows
  sample outputs, so anyone can see the value in 2 minutes.
Run:  streamlit run app.py
"""
from __future__ import annotations

import json
import os

import streamlit as st

# Cloud bridge: on Streamlit Cloud the key arrives via st.secrets, not
# a .env file. Mirror it into the environment BEFORE src.config builds
# the key manager, so the rest of the app sees no difference.
try:
    for _k in ("GOOGLE_API_KEYS", "LLM_MODEL"):
        if _k in st.secrets and not os.environ.get(_k):
            os.environ[_k] = str(st.secrets[_k])
except Exception:
    pass

from src import config, memory
from src.config import KEY_MANAGER

st.set_page_config(page_title="CreatorCrew RAG", page_icon="🎬",
                   layout="wide")

DEMO_SCRIPT = {
    "topic": "Demo: 3 mistakes that kill a new channel",
    "youtube": {
        "hook": "Your first 10 videos will fail — unless you fix this one thing.",
        "retention_body": "[Demo output] Open with the mistake, show the fix, "
                          "tease the second mistake at 0:30, deliver, then the third.",
        "cta": "Subscribe for one growth breakdown every day.",
        "seo_title": "3 Mistakes That Kill New YouTube Channels (Fix Them Fast)",
        "description": "Demo description generated in Demo Mode.",
        "tags": ["youtube growth", "new creators", "demo"],
    },
    "facebook": {
        "reel_hook": "Stop posting Reels like this — do THIS instead.",
        "pacing_notes": "Cut every 2-3 seconds, captions on, payoff at 0:25.",
        "caption": "Demo caption — which mistake are YOU making? 👇",
    },
    "citations": ["demo-mode"],
}


@st.cache_resource(show_spinner="Loading knowledge base…")
def load_store():
    from src.ingest import get_vectorstore
    return get_vectorstore()


def kb_size() -> int:
    try:
        return len(load_store().get(include=[])["ids"])
    except Exception:
        return 0


@st.cache_resource(show_spinner=False)
def ensure_kb() -> int:
    """Self-healing knowledge base. Hosts with temporary storage
    (e.g. Streamlit Cloud) start with an empty index, so rebuild it
    once from the configured public sources. A failure here never
    blocks the app — Demo Mode and generation still work."""
    try:
        n = kb_size()
        if n == 0:
            with st.spinner("📚 First run on this host: building the "
                            "knowledge base (a few minutes, one time only)…"):
                from src.ingest import build_index
                build_index()
            n = kb_size()
        return n
    except Exception:
        return 0


def friendly_error(e: Exception) -> None:
    msg = str(e)
    if "demo mode" in msg.lower() or "No API key" in msg:
        st.warning("🔑 This feature needs a free Gemini API key. "
                   "Add GOOGLE_API_KEYS to your .env file — see the sidebar. "
                   "Meanwhile, Demo Mode shows you sample outputs.")
    elif "All API keys failed" in msg:
        st.error("All API keys are down.")
        st.code(KEY_MANAGER.REGENERATION_STEPS)
    else:
        st.error(f"Something went wrong: {msg[:300]}")


# ---------------------------------------------------------------------------
# Sidebar — creator settings (long-term memory) + key status [C15]
# ---------------------------------------------------------------------------
profile = memory.get_profile()
with st.sidebar:
    st.header("🎛️ Creator Settings")
    niche = st.text_input("Niche", profile.get("niche", ""),
                          help="What is your channel/page about?")
    audience = st.text_input("Target audience", profile.get("audience", ""),
                             help="Who are you creating for?")
    tone = st.selectbox("Tone", ["bold", "friendly", "educational", "funny"],
                        index=["bold", "friendly", "educational", "funny"].index(
                            profile.get("tone") or "friendly"),
                        help="The voice of your scripts.")
    channel = st.text_input("Channel / Page name", profile.get("channel_name", ""))
    if st.button("💾 Save settings", use_container_width=True):
        memory.set_profile(niche=niche, audience=audience, tone=tone,
                           channel_name=channel)
        st.success("Saved — the agents will use these from now on.")

    st.divider()
    ks = KEY_MANAGER.status()
    icon = {"active": "🟢", "no_key": "🟡", "down": "🔴"}.get(ks["state"], "⚪")
    st.markdown(f"**API Key:** {icon} {ks['label']}")
    if ks["state"] == "no_key":
        st.caption("Get a free key (no card): aistudio.google.com/apikey — "
                   "then paste it into .env as GOOGLE_API_KEYS.")
    if ks["state"] == "down":
        st.code(KEY_MANAGER.REGENERATION_STEPS)
    st.caption(f"Knowledge base: {kb_size()} chunks indexed")

# ---------------------------------------------------------------------------
# Home dashboard — stat cards + big actions
# ---------------------------------------------------------------------------
ensure_kb()
st.title("🎬 CreatorCrew RAG")
st.caption("Free multi-agent content & video automation studio for YouTube and Facebook.")
stats = memory.stats()
c1, c2, c3, c4 = st.columns(4)
c1.metric("📚 Documents indexed", kb_size())
c2.metric("✍️ Scripts generated", stats["scripts"])
c3.metric("🎞️ Clips rendered", stats["clips"])
c4.metric("🔑 API key", KEY_MANAGER.status()["label"][:28])

tab_home, tab_studio, tab_transform, tab_split, tab_eval = st.tabs(
    ["🏠 Home", "✍️ Content Studio", "🔗 Link Transformer",
     "✂️ Viral Splitter", "📊 Evaluation & History"])

with tab_home:
    st.subheader("What do you want to do?")
    a, b, cc = st.columns(3)
    a.info("✍️ **Write a Script**\n\nGo to the Content Studio tab: give a "
           "topic, get a YouTube + Facebook package checked by the Critic.")
    b.info("🔗 **Transform a Link**\n\nPaste a video/article link in the "
           "Transformer tab: get a 100% original script with a fresh angle.")
    cc.info("✂️ **Make Short Clips**\n\nOpen the Viral Splitter tab: turn a "
            "long video you own into ready-to-post vertical clips.")
    st.subheader("How it works")
    st.markdown(
        "1. **Planner** reads your creator profile and plans the content.\n"
        "2. **Researcher** searches the knowledge base (viral patterns + "
        "official YouTube/Meta policy).\n"
        "3. **Scriptwriter** drafts YouTube + Facebook packages.\n"
        "4. **Critic** audits compliance & originality (max 2 revisions).\n\n"
        "Everything runs on free tools and your own free Gemini key.")

# ---------------------------------------------------------------------------
# Tab 1 — Content Studio
# ---------------------------------------------------------------------------
with tab_studio:
    st.subheader("Step 1 — Your topic")
    topic = st.text_input("Topic", placeholder="e.g. 5 AI tools for students",
                          help="What should today's content be about?")
    st.subheader("Step 2 — Run the agent team")
    if st.button("🚀 Generate scripts", type="primary",
                 disabled=not topic):
        if not KEY_MANAGER.has_keys:
            st.info("Demo Mode — sample output (add a key for real generation):")
            st.json(DEMO_SCRIPT)
        else:
            with st.spinner("Agents working: plan → research → write → audit…"):
                try:
                    from src.agents import run_content_studio
                    result = run_content_studio(topic)
                    st.success("Done — Critic-approved package:")
                    st.json(result["draft"])
                    st.markdown("**Critic report**")
                    st.json(result["critic"])
                    st.download_button(
                        "⬇️ Download script package (JSON)",
                        json.dumps(result, indent=2),
                        file_name="script-package.json")
                except Exception as e:
                    friendly_error(e)

# ---------------------------------------------------------------------------
# Tab 2 — Link Transformer
# ---------------------------------------------------------------------------
with tab_transform:
    st.subheader("Step 1 — Paste a link")
    url = st.text_input("Video or article URL",
                        placeholder="https://…",
                        help="Ideas are extracted and rewritten — the "
                             "original media is never re-uploaded.")
    st.subheader("Step 2 — Transform it into an original script")
    if st.button("🔗 Transform link", type="primary", disabled=not url):
        with st.spinner("Extracting ideas → writing original script → "
                        "measuring originality…"):
            try:
                from src.transformer import transform_link
                res = transform_link(url)
                st.success(f"Original script ready — overlap with source: "
                           f"{res.overlap_pct}% (limit 25%)")
                st.markdown(f"**Fresh angle:** {res.angle}")
                st.markdown("**Core ideas used:**")
                for idea in res.source_ideas:
                    st.markdown(f"- {idea}")
                st.text_area("Your original script", res.original_script,
                             height=300)
                st.download_button("⬇️ Download script (.txt)",
                                   res.original_script,
                                   file_name="original-script.txt")
            except Exception as e:
                friendly_error(e)

# ---------------------------------------------------------------------------
# Tab 3 — Viral Splitter
# ---------------------------------------------------------------------------
with tab_split:
    st.subheader("Step 1 — Rights declaration (required)")
    rights = st.selectbox(
        "I confirm this video is…",
        ["", "own", "licensed", "public-domain", "creative-commons"],
        help="The splitter only processes content you have the rights to "
             "use. This declaration is saved with every clip.")
    source_note = st.text_input("Source note",
                                placeholder="e.g. My own recording, 12 Nov",
                                help="Where this video comes from — your "
                                     "safety record.")
    st.subheader("Step 2 — Long video source")
    src_url = st.text_input("Video URL (yours / licensed / public domain)")
    uploaded = st.file_uploader("…or upload a video file",
                                type=["mp4", "mov", "mkv", "webm"])
    clip_len = st.radio("Clip length", [30, 60], horizontal=True,
                        format_func=lambda s: f"{s} seconds")
    reframe = st.radio("Vertical framing", ["blur", "crop"], horizontal=True,
                       format_func=lambda s: "Blurred background" if s == "blur"
                       else "Centre crop")
    st.subheader("Step 3 — Detect & render viral clips")
    if st.button("✂️ Create clips", type="primary"):
        if not rights:
            st.warning("Please complete the rights declaration first.")
        elif not source_note.strip():
            st.warning("Please add a source note first.")
        elif not src_url and not uploaded:
            st.warning("Give a video URL or upload a file first.")
        else:
            try:
                source = src_url
                if uploaded is not None:
                    tmp = config.SHORTS_DIR / "_work" / uploaded.name
                    tmp.parent.mkdir(parents=True, exist_ok=True)
                    if uploaded.size > config.MAX_UPLOAD_MB * 1024 * 1024:
                        raise ValueError(
                            f"File too large — limit is {config.MAX_UPLOAD_MB} MB.")
                    tmp.write_bytes(uploaded.getbuffer())
                    source = str(tmp)
                with st.spinner("Finding viral scenes and rendering clips… "
                                "(this can take a few minutes)"):
                    from src.splitter import split_video
                    results = split_video(source, rights, source_note,
                                          clip_len=clip_len, reframe=reframe)
                st.success(f"{len(results)} clip(s) ready:")
                for meta in results:
                    fpath = config.SHORTS_DIR / meta["file"]
                    st.markdown(f"**{meta['file']}** — {meta['hook'][:80]}…")
                    st.caption(f"⏱ {meta['start_sec']}s → {meta['end_sec']}s · "
                               f"{meta['reason']}")
                    st.download_button(
                        f"⬇️ Download {meta['file']}",
                        fpath.read_bytes(), file_name=meta["file"],
                        key=f"dl-{meta['file']}")
            except Exception as e:
                friendly_error(e)

# ---------------------------------------------------------------------------
# Tab 4 — Evaluation & History
# ---------------------------------------------------------------------------
with tab_eval:
    st.subheader("Evaluation")
    report_path = config.OUTPUTS_DIR / "eval_report.json"
    if report_path.exists():
        rep = json.loads(report_path.read_text(encoding="utf-8"))
        st.markdown(f"Engine: `{rep.get('engine', '-')}`")
        av = rep.get("averages", {})
        e1, e2, e3 = st.columns(3)
        e1.metric("Faithfulness", av.get("faithfulness", "-"))
        e2.metric("Compliance", av.get("compliance", "-"))
        e3.metric("Relevance", av.get("relevance", "-"))
        with st.expander("Per-question scores"):
            st.json(rep.get("scores", []))
    else:
        st.info("No evaluation yet. Run it from your terminal: "
                "`python -m tests.evaluate_ragas` (needs a Gemini key).")
    if config.os.getenv("LANGCHAIN_API_KEY"):
        st.markdown("LangSmith tracing is ON — project: "
                    f"`{config.os.getenv('LANGCHAIN_PROJECT', 'CreatorCrew-RAG')}` "
                    "at smith.langchain.com")
    else:
        st.caption("LangSmith tracing is OFF (optional — add LANGCHAIN_API_KEY "
                   "to .env to enable it).")

    st.subheader("History — your past outputs")
    rows = memory.list_outputs(15)
    if not rows:
        st.info("Nothing yet — generate your first script in the Studio tab.")
    for r in rows:
        with st.expander(f"#{r['id']} · {r['kind']} · {r['topic'][:60]} · "
                         f"{r['created_at'][:16].replace('T', ' ')}"):
            st.json(r["content"])
            if r["critic"]:
                st.caption(f"Critic: {json.dumps(r['critic'])[:400]}")
