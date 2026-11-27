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
from pathlib import Path

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
from video_settings import render_clip_settings

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


@st.cache_data(ttl=600, show_spinner=False)
def _key_verified(masked: str, active_idx: int) -> bool:
    """Real health check of the active key, cached for 10 minutes.
    The sidebar may only claim "Key active" for a key that actually
    answered the Gemini API [Phase 0]."""
    try:
        return KEY_MANAGER.health_check(timeout=6)
    except Exception:
        return False


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


def _render_pack(pack, template_name, topic_text, key_prefix):
    """Render one generated production pack: title, hook, the timed
    beats with copyable visual prompts, CTA, caption, hashtags — plus
    the one-file markdown download. Shared by the Content Studio
    generation surface and the Master Prompt tab's topic library."""
    from src import generators, master_prompt
    from src.schemas import MasterPromptTemplate
    pack_tpl = (master_prompt.load(template_name)
                or MasterPromptTemplate(name=template_name))
    if pack.get("title"):
        st.markdown(f"**{pack['title']}**")
    if pack.get("hook"):
        st.markdown(f"**Hook:** {pack['hook']}")
    _total = int(float(pack.get("total_duration_sec") or 0))
    st.caption(f"Total duration: ~{_total // 60}:{_total % 60:02d} "
               f"({_total}s)")
    for i, beat in enumerate(pack.get("beats") or [], start=1):
        _start = int(float(beat.get("start_sec") or 0))
        st.markdown(f"**Beat {i} · {_start // 60}:{_start % 60:02d}**")
        st.markdown(beat.get("narration", ""))
        if beat.get("visual_prompt"):
            st.code(beat["visual_prompt"])
        if beat.get("on_screen_text"):
            st.markdown(f"On-screen text: {beat['on_screen_text']}")
        if beat.get("music_cue"):
            st.markdown(f"Music: {beat['music_cue']}")
    if pack.get("cta"):
        st.markdown(f"**CTA:** {pack['cta']}")
    if pack.get("caption"):
        st.markdown("**Caption:**")
        st.markdown(pack["caption"])
    if pack.get("hashtags"):
        st.markdown(f"**Hashtags:** {pack['hashtags']}")
    st.download_button(
        "⬇️ Download production pack (.md)",
        generators.format_production_pack(pack_tpl, topic_text, pack),
        file_name="production-pack.md",
        key=f"mp_pack_dl_{key_prefix}")


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
    if ks["state"] == "active":
        if _key_verified(ks["active"], KEY_MANAGER.active):
            icon = "🟢"
            key_status_label = f"Key active {ks['active']} (verified)"
        else:
            icon = "🔴"
            key_status_label = (f"Key {ks['active']} is present but NOT "
                                "answering — it may be wrong, revoked or "
                                "out of quota")
    else:
        icon = {"no_key": "🟡", "down": "🔴"}.get(ks["state"], "⚪")
        key_status_label = ks["label"]
    st.markdown(f"**API Key:** {icon} {key_status_label}")
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
c4.metric("🔑 API key", key_status_label[:28])

tab_home, tab_studio, tab_transform, tab_split, tab_eval, tab_master = \
    st.tabs(["🏠 Home", "✍️ Content Studio", "🔗 Link Transformer",
             "✂️ Viral Splitter", "📊 Evaluation & History",
             "🎬 Master Prompt"])

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
                    if result["critic"].get("verdict") == "pass" and \
                            result["critic"].get("compliance_ok"):
                        st.success("Done — Critic-approved package:")
                    else:
                        st.warning("Done — but this package NEEDS REVIEW: "
                                   "the Critic did not approve it.")
                    st.json(result["draft"])
                    st.markdown("**Critic report**")
                    st.json(result["critic"])
                    st.download_button(
                        "⬇️ Download script package (JSON)",
                        json.dumps(result, indent=2),
                        file_name="script-package.json")
                except Exception as e:
                    friendly_error(e)

    # ------------------------------------------------------------------
    # Master Prompt generation — the Zero-to-Hero work surface.
    # 1) A complete locked master prompt from ONLY a niche name.
    # 2) A topic's full production pack from a LOCKED master prompt.
    # All generation lives here, in the content-creator section; the
    # 🎬 Master Prompt tab stays the library (lock / edit / view).
    # ------------------------------------------------------------------
    st.divider()
    st.subheader("🎬 Master Prompt — Zero to Hero")
    st.caption("Pehle niche se master prompt banao, phir usi locked "
               "template se sirf topic par poora production pack.")

    from src import generators, master_prompt

    st.markdown("**1 — Master prompt banao (sirf niche se)**")
    col_sn, col_sb = st.columns([4, 1])
    with col_sn:
        studio_niche = st.text_input(
            "Niche", key="studio_mp_niche",
            placeholder="e.g. deep sea creatures / home fitness for "
                        "beginners / classic muscle cars")
    with col_sb:
        st.write("")  # align the button with the input box
        studio_gen_tpl_clicked = st.button(
            "🎬 Generate master prompt", key="studio_mp_gen_btn")
    if studio_gen_tpl_clicked:
        clean_niche = (studio_niche or "").strip()
        if not clean_niche:
            st.error("Pehle niche ka naam likho.")
        else:
            try:
                with st.spinner("Premium standard se master prompt "
                                "tayyar ho raha hai…"):
                    new_tpl = generators.generate_template_from_niche(
                        clean_niche)
                if master_prompt.load(new_tpl.name) is not None:
                    # Name collision: load the generated values into
                    # the Master Prompt tab's form (its widgets render
                    # later this run, so setting the keys is safe) —
                    # nothing is overwritten until he reviews + Locks
                    # there.
                    st.session_state["mp_name"] = new_tpl.name
                    st.session_state["mp_characters"] = (
                        master_prompt.format_characters(
                            [c.model_dump() for c in new_tpl.characters]))
                    st.session_state["mp_visual_style"] = (
                        new_tpl.visual_style)
                    st.session_state["mp_negative"] = (
                        new_tpl.negative_prompt)
                    st.session_state["mp_format"] = new_tpl.target_format
                    st.session_state["mp_beats"] = int(new_tpl.beat_count)
                    st.session_state["mp_hook"] = new_tpl.hook_style
                    st.session_state["mp_cta"] = new_tpl.cta
                    st.session_state["mp_language"] = new_tpl.language
                    st.session_state["mp_tone"] = new_tpl.tone
                    st.session_state["mp_caption"] = new_tpl.caption_style
                    st.session_state["mp_hashtags"] = new_tpl.hashtags
                    st.session_state["mp_loaded_for"] = (
                        st.session_state.get("mp_choice",
                                             "➕ New template"))
                    st.session_state["mp_notice"] = (
                        f"“{new_tpl.name}” ki nayi generated values "
                        "form mein bhar di gayi hain — review karke "
                        "Lock karo.")
                    st.warning(
                        f"“{new_tpl.name}” naam ka template pehle se "
                        "maujud hai — nayi generated values 🎬 Master "
                        "Prompt tab ke form mein bhar di hain. Wahan "
                        "review karke isi naam par Lock karo, ya naam "
                        "badal kar Lock karo; tab tak purana template "
                        "mehfooz hai.")
                else:
                    master_prompt.save(new_tpl)
                    st.session_state["mp_choice"] = new_tpl.name
                    st.session_state.pop("mp_loaded_for", None)
                    st.success(
                        f"🎬 Master prompt tayyar aur lock ho gaya: "
                        f"“{new_tpl.name}” — "
                        f"{len(new_tpl.characters)} characters, "
                        f"{new_tpl.target_format}. Ab neeche step 2 "
                        "mein isi se topic pack banao.")
            except Exception as e:
                friendly_error(e)

    st.markdown("**2 — Topic generate karo**")
    studio_templates = master_prompt.list_names()
    if not studio_templates:
        st.info("Abhi koi master prompt saved nahi hai — upar step 1 "
                "se banao, ya 🎬 Master Prompt tab mein lock karo.")
    else:
        studio_tpl_name = st.selectbox("Master prompt",
                                       studio_templates,
                                       key="studio_mp_select")
        col_st, col_sgb = st.columns([4, 1])
        with col_st:
            studio_topic = st.text_input(
                "Topic", key="studio_mp_topic",
                placeholder="e.g. Gus tries to cook a giant pancake")
        with col_sgb:
            st.write("")  # align the button with the input box
            studio_gen_pack_clicked = st.button(
                "🎬 Generate topic pack", key="studio_mp_gen_pack_btn")
        if studio_gen_pack_clicked:
            clean_topic = (studio_topic or "").strip()
            if not clean_topic:
                st.error("Pehle topic likho.")
            else:
                existing = next(
                    (t for t in master_prompt.list_topics(
                        studio_tpl_name)
                     if t.topic.strip().lower()
                     == clean_topic.lower()), None)
                topic_row = existing or master_prompt.add_topic(
                    studio_tpl_name, clean_topic)
                try:
                    with st.spinner("Locked template se production "
                                    "pack ban raha hai…"):
                        pack = generators.generate_topic_pack(
                            master_prompt.load(studio_tpl_name),
                            clean_topic)
                    master_prompt.save_topic_result(topic_row.id, pack)
                    st.success(
                        f"🎬 Pack tayyar — “{clean_topic}” ke neeche "
                        f"auto-save ho gaya (“{studio_tpl_name}”). "
                        "Ye pack 🎬 Master Prompt tab mein bhi mehfooz "
                        "hai.")
                    _render_pack(pack, studio_tpl_name, clean_topic,
                                 f"studio_{topic_row.id}")
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
                if res.needs_review:
                    st.warning(f"Script ready, but it is still too close "
                               f"to the source — overlap: "
                               f"{res.overlap_pct}% (limit 25%). "
                               f"Review it by hand before use.")
                else:
                    st.success(f"Original script ready — overlap with "
                               f"source: {res.overlap_pct}% (limit 25%)")
                st.markdown(f"**Fresh angle:** {res.angle}")
                st.markdown("**Core ideas used:**")
                for idea in res.source_ideas:
                    st.markdown(f"- {idea}")
                if res.beats:
                    st.markdown("**Scene beats — production prompts:**")
                    for i, beat in enumerate(res.beats, start=1):
                        start = int(beat.start_sec)
                        st.markdown(f"**Beat {i} · "
                                    f"{start // 60}:{start % 60:02d}**")
                        st.markdown(beat.narration)
                        st.code(beat.visual_prompt)
                        if beat.on_screen_text:
                            st.markdown("On-screen text: "
                                        f"{beat.on_screen_text}")
                if res.cta:
                    st.markdown(f"**CTA:** {res.cta}")
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
    from src.editing import intake as _intake
    from src.editing import presets as _presets
    from src.editing import registry as _registry
    _registry.load_operations()

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

    st.subheader("Step 2 — Choose your video")
    src_mode = st.radio("Video source",
                        ["Upload a file", "Direct media URL",
                         "My video URL (YouTube etc.)", "Media library"],
                        horizontal=True,
                        help="Uploads and direct media-file URLs are "
                             "validated and stored in your media "
                             "library. 'My video URL' fetches one of "
                             "YOUR OWN videos from a watch page (e.g. "
                             "your YouTube channel) under the same "
                             "rights declaration.")
    pending = None          # (kind, value) waiting to be added to library
    if src_mode == "Upload a file":
        uploaded = st.file_uploader("Video file (MP4, MOV, MKV, WebM)",
                                    type=["mp4", "mov", "mkv", "webm"],
                                    key="sp_upload")
        if uploaded is not None:
            pending = ("upload", uploaded)
    elif src_mode == "Direct media URL":
        src_url = st.text_input(
            "Direct media URL",
            placeholder="https://…/my-video.mp4",
            help="Must point directly at a media file you own or are "
                 "licensed to use.", key="sp_url")
        if src_url.strip():
            pending = ("url", src_url.strip())
    elif src_mode == "My video URL (YouTube etc.)":
        watch_url = st.text_input(
            "Your video's watch-page URL",
            placeholder="https://www.youtube.com/watch?v=…",
            help="For YOUR OWN videos only — the rights declaration "
                 "above applies and is saved with every clip. The "
                 "video is fetched at up to 720p to save space.",
            key="sp_watch_url")
        st.checkbox(
            "Delete the downloaded video after rendering (save space)",
            value=True, key="sp_autodel",
            help="The downloaded long video is removed once your "
                 "clips are rendered — only the clips stay on disk. "
                 "The rights record is kept in each clip's JSON.")
        if watch_url.strip():
            pending = ("watch", watch_url.strip())
    else:
        items = _intake.list_library()
        if not items:
            st.info("Your media library is empty — upload a file or add "
                    "a direct media URL first.")
        else:
            labels = {f"{it['name']} · {it['duration']:.0f}s · "
                      f"{it['size_mb']} MB": it["id"] for it in items}
            pick = st.selectbox("Previously added videos", list(labels))
            st.session_state["sp_source"] = _intake.get_library_item(
                labels[pick])

    if pending is not None and st.button("📥 Validate & add to library"):
        if not rights:
            st.warning("Please complete the rights declaration first.")
        elif not source_note.strip():
            st.warning("Please add a source note first.")
        else:
            try:
                with st.spinner("Validating and storing your video…"):
                    if pending[0] == "upload":
                        f = pending[1]
                        if f.size > config.MAX_UPLOAD_MB * 1024 * 1024:
                            raise ValueError(
                                f"File too large — limit is "
                                f"{config.MAX_UPLOAD_MB} MB.")
                        tmp = config.SHORTS_DIR / "_work" / f.name
                        tmp.parent.mkdir(parents=True, exist_ok=True)
                        tmp.write_bytes(f.getbuffer())
                        entry = _intake.add_to_library(
                            str(tmp), rights, source_note)
                    elif pending[0] == "watch":
                        entry = _intake.add_watch_url_to_library(
                            pending[1], rights, source_note)
                        st.session_state["sp_autodelete"] = bool(
                            st.session_state.get("sp_autodel", True))
                    else:
                        entry = _intake.add_to_library(
                            pending[1], rights, source_note)
                st.session_state["sp_source"] = entry
                st.success(f"Added to library: {entry['name']} "
                           f"({entry['duration']:.0f}s, {entry['size_mb']} MB)")
            except Exception as e:
                friendly_error(e)

    sp_source = st.session_state.get("sp_source")
    if sp_source and not Path(sp_source["path"]).exists():
        # e.g. a URL-fetched source that was auto-deleted after a
        # render to save disk space.
        st.session_state.pop("sp_source", None)
        st.info("The previously selected video's file is no longer "
                "on disk (URL-fetched sources are deleted after "
                "rendering when the save-space option is on). "
                "Please choose a video again.")
        sp_source = None
    if sp_source:
        st.caption(f"🎬 Selected: **{sp_source['name']}** · "
                   f"{sp_source['duration']:.0f}s · "
                   f"{sp_source['width']}×{sp_source['height']} · "
                   f"rights: {sp_source['rights']}")

    st.subheader("Step 3 — Find scenes & adjust timestamps")
    clip_settings = render_clip_settings(key_prefix="sp")
    clip_len = clip_settings["duration_seconds"]
    num_clips = clip_settings["clip_count"]
    whisper_model = st.radio(
        "Speech engine", ["tiny", "base"], index=1, horizontal=True,
        format_func=lambda m: ("⚡ Ultra-Fast (Tiny — 5x speed)"
                               if m == "tiny" else
                               "🎯 High Accuracy (Base)"),
        key="sp_whisper",
        help="Base is the default — it hears difficult words more "
             "accurately; Tiny transcribes much faster on CPU.")
    config.WHISPER_MODEL = whisper_model
    if st.button("🔍 Detect scenes", type="primary"):
        if not sp_source:
            st.warning("Choose a video in Step 2 first.")
        else:
            try:
                with st.spinner("Listening to the video and scoring "
                                "scenes… (this can take a few minutes)"):
                    from src import tools as _tools
                    from src.editing import scoring as _scoring
                    from src.splitter import propose_candidates
                    tr = _tools.get_transcript(
                        sp_source["path"], whisper_model=whisper_model)
                    if not tr or not tr.get("segments"):
                        raise RuntimeError(
                            "No transcript/timestamps could be produced "
                            "for this video, so scenes cannot be detected.")
                    cands = propose_candidates(tr["segments"], clip_len,
                                               num_clips)
                    ranked = _scoring.rank_candidates(
                        [{"start_sec": c.start_sec, "end_sec": c.end_sec,
                          "hook": c.hook} for c in cands], tr["segments"])
                    by_span = {(r["start_sec"], r["end_sec"]): r
                               for r in ranked}
                st.session_state["sp_candidates"] = [
                    {"start_sec": c.start_sec, "end_sec": c.end_sec,
                     "hook": c.hook, "reason": c.reason,
                     "score": by_span.get(
                         (c.start_sec, c.end_sec), {}).get("score"),
                     "breakdown": by_span.get(
                         (c.start_sec, c.end_sec), {}).get("breakdown"),
                     "rationale": by_span.get(
                         (c.start_sec, c.end_sec), {}).get("rationale")}
                    for c in cands]
                st.session_state["sp_cand_ver"] = \
                    st.session_state.get("sp_cand_ver", 0) + 1
                st.session_state["sp_word_timings"] = \
                    _tools.word_timings_label(tr["segments"])
                st.success(f"{len(cands)} scene(s) found — ranked by "
                           "Virality potential (heuristic). Adjust the "
                           "timestamps below if you like.")
            except Exception as e:
                friendly_error(e)

    edited_clips = []
    cands = st.session_state.get("sp_candidates", [])
    cver = st.session_state.get("sp_cand_ver", 0)
    for i, c in enumerate(cands):
        score_txt = (f"⭐ Virality potential (heuristic) "
                     f"{c['score']:.0f}/100 · "
                     if c.get("score") is not None else "")
        with st.expander(f"Clip {i + 1} — {score_txt}"
                         f"{c['start_sec']:.0f}s → "
                         f"{c['end_sec']:.0f}s · {c['hook'][:60]}…",
                         expanded=(i == 0)):
            st.caption(c["reason"])
            if c.get("breakdown"):
                st.markdown("**Virality potential (heuristic) — "
                            "breakdown** (0–100 per dimension)")
                st.json(c["breakdown"])
            col_a, col_b = st.columns(2)
            s_val = col_a.number_input(
                "Start (seconds)", min_value=0.0, step=0.5,
                value=float(c["start_sec"]), key=f"cand{cver}_{i}_start")
            e_val = col_b.number_input(
                "End (seconds)", min_value=0.5, step=0.5,
                value=float(c["end_sec"]), key=f"cand{cver}_{i}_end")
            h_val = st.text_input("Hook text", value=c["hook"],
                                  key=f"cand{cver}_{i}_hook")
            edited_clips.append({"start_sec": s_val, "end_sec": e_val,
                                 "hook": h_val, "reason": c["reason"],
                                 "virality_score": c.get("score"),
                                 "score_breakdown": c.get("breakdown"),
                                 "score_rationale": c.get("rationale")})

    st.subheader("Step 4 — Editing options")
    if "sp_seed" not in st.session_state:
        st.session_state["sp_seed"] = _presets.build_config("Minimal")
        st.session_state["sp_ver"] = 0
    pcol1, pcol2 = st.columns([3, 1])
    preset_name = pcol1.selectbox("Preset", _presets.PRESET_NAMES,
                                  key="sp_preset_name",
                                  help="Professional / Cinematic / Social "
                                       "Media turn on sensible bundles. "
                                       "Minimal = the classic splitter look. "
                                       "Change any toggle to make it yours.")
    if pcol2.button("Apply preset"):
        st.session_state["sp_seed"] = _presets.build_config(preset_name)
        st.session_state["sp_ver"] += 1
        st.rerun()
    seed = st.session_state["sp_seed"]
    ver = st.session_state["sp_ver"]

    extras_dir = config.SHORTS_DIR / "_work" / "extras"
    extras_dir.mkdir(parents=True, exist_ok=True)
    ecol1, ecol2, ecol3 = st.columns(3)
    bgm_up = ecol1.file_uploader("Background music (optional)",
                                 type=["mp3", "wav", "ogg", "m4a"],
                                 key="sp_bgm")
    pip_up = ecol2.file_uploader("Picture-in-picture video (optional)",
                                 type=["mp4", "mov", "mkv", "webm"],
                                 key="sp_pip")
    logo_up = ecol3.file_uploader("Logo image (optional)",
                                  type=["png", "jpg", "jpeg"],
                                  key="sp_logo")
    extras = {}
    for _up, _key in ((bgm_up, "bgm_path"), (pip_up, "pip_path"),
                      (logo_up, "logo_path")):
        if _up is not None:
            _p = extras_dir / _up.name
            _p.write_bytes(_up.getbuffer())
            st.session_state[f"sp_{_key}"] = str(_p)
        if st.session_state.get(f"sp_{_key}"):
            extras[_key] = st.session_state[f"sp_{_key}"]
    cap_keywords = st.text_input(
        "Caption emphasis keywords (optional)",
        placeholder="e.g. secret, mistake, free",
        help="These words are highlighted in the burned-in captions.",
        key="sp_keywords")

    ui_config = {}
    for op in _registry.ordered_ops():
        ocfg = seed.get(op.id, {"enabled": False, "params": op.defaults()})
        enabled = st.checkbox(op.label, value=bool(ocfg.get("enabled")),
                              help=op.help, key=f"sp{ver}_{op.id}_en")
        params = dict(op.defaults())
        params.update(ocfg.get("params", {}))
        if enabled:
            for p in op.params:
                k = f"sp{ver}_{op.id}_{p['key']}"
                cur = params.get(p["key"], p["default"])
                if p["type"] == "bool":
                    params[p["key"]] = st.checkbox(p["label"], value=bool(cur),
                                                   help=p.get("help"), key=k)
                elif p["type"] in ("float", "int"):
                    lo, hi = p.get("min"), p.get("max")
                    if lo is not None and hi is not None:
                        v = st.slider(p["label"], min_value=lo, max_value=hi,
                                      value=type(lo)(cur), step=p.get("step", 1),
                                      help=p.get("help"), key=k)
                    else:
                        v = st.number_input(p["label"], value=cur,
                                            help=p.get("help"), key=k)
                    params[p["key"]] = v
                elif p["type"] == "select":
                    params[p["key"]] = st.selectbox(
                        p["label"], p["choices"],
                        index=p["choices"].index(cur)
                        if cur in p["choices"] else 0,
                        help=p.get("help"), key=k)
                elif p["type"] == "text":
                    params[p["key"]] = st.text_input(
                        p["label"], value=str(cur), help=p.get("help"), key=k)
        ui_config[op.id] = {"enabled": enabled, "params": params}
    if cap_keywords.strip():
        ui_config["captions"]["params"]["keywords"] = cap_keywords.strip()
    for _k in ("bgm_path", "pip_path", "logo_path"):
        if _k in extras:
            _op = {"bgm_path": "bgm", "pip_path": "pip",
                   "logo_path": "logo_overlay"}[_k]
            ui_config[_op]["params"][_k] = extras[_k]

    st.subheader("Step 5 — Render & download")
    if st.button("✂️ Render clips", type="primary"):
        if not sp_source:
            st.warning("Choose a video in Step 2 first.")
        elif not edited_clips:
            st.warning("Detect scenes in Step 3 first.")
        else:
            try:
                from src.editing import pipeline as _pipeline
                bar = st.progress(0.0)
                status = st.empty()
                results = []
                n = len(edited_clips)
                for idx, c in enumerate(edited_clips, 1):
                    if c["end_sec"] <= c["start_sec"]:
                        raise ValueError(
                            f"Clip {idx}: end must be after start.")

                    def _cb(op_id, i, total, _idx=idx):
                        frac = ((_idx - 1) + (i / max(total, 1))) / n
                        bar.progress(min(frac, 1.0))
                        status.caption(f"Clip {_idx}/{n}: {op_id}…")

                    out = config.SHORTS_DIR / f"clip-{idx:02d}.mp4"
                    res = _pipeline.render_segment(
                        sp_source["path"], c["start_sec"], c["end_sec"],
                        ui_config, out,
                        config.SHORTS_DIR / "_work" / f"ui-{idx}",
                        extras={**extras, "hook_text": c["hook"]},
                        progress_cb=_cb)
                    meta = {**c, "rights": sp_source["rights"],
                            "source_note": sp_source["source_note"],
                            "source": sp_source["source"],
                            "file": out.name, "applied": res["applied"],
                            "warnings": res["warnings"],
                            "word_timings": st.session_state.get(
                                "sp_word_timings")}
                    (config.SHORTS_DIR / f"clip-{idx:02d}.json").write_text(
                        json.dumps(meta, indent=2), encoding="utf-8")
                    from src import memory as _memory
                    _memory.save_output("clip", sp_source["source"], "shorts",
                                        {"file": out.name, "hook": c["hook"]},
                                        {"rights": sp_source["rights"]})
                    results.append(meta)
                bar.progress(1.0)
                status.empty()
                st.session_state["sp_results"] = results
                st.success(f"{len(results)} clip(s) rendered:")
                if (sp_source.get("origin_kind") == "watch-url"
                        and st.session_state.get("sp_autodelete", True)
                        and _intake.remove_from_library(sp_source["id"])):
                    st.info("🗑️ Save-space: the downloaded long video "
                            "was deleted — only your clips remain on "
                            "disk. The rights record is kept in each "
                            "clip's JSON file.")
            except Exception as e:
                friendly_error(e)

    for meta in st.session_state.get("sp_results", []):
        fpath = config.SHORTS_DIR / meta["file"]
        if not fpath.exists():
            continue
        st.markdown(f"**{meta['file']}** — {meta['hook'][:80]}…")
        st.caption(f"⏱ {meta['start_sec']}s → {meta['end_sec']}s · "
                   f"effects: {', '.join(meta.get('applied', [])) or 'none'}")
        for w in meta.get("warnings", []):
            st.warning(w)
        st.video(str(fpath))
        st.download_button(f"⬇️ Download {meta['file']}",
                           fpath.read_bytes(), file_name=meta["file"],
                           key=f"dl2-{meta['file']}")
    _results = st.session_state.get("sp_results", [])
    if len(_results) > 1:
        from src.editing import export as _export
        _files = []
        for m in _results:
            _files.append(config.SHORTS_DIR / m["file"])
            _files.append(config.SHORTS_DIR /
                          (Path(m["file"]).stem + ".json"))
        _zip = _export.make_zip(_files, config.SHORTS_DIR / "clips.zip")
        st.download_button("⬇️ Download all clips (ZIP)",
                           _zip.read_bytes(), file_name="clips.zip",
                           key="dl2-zip")

    st.subheader("Step 6 — Transformation plan (optional)")
    st.caption("A 7-stage editorial editing plan for the clip above — "
               "built on your own commentary. Uses the rights declaration "
               "and source note from Step 1.")
    plan_platform = st.text_input(
        "Target platform & format",
        placeholder="e.g. YouTube Shorts 9:16, Facebook Reels, YouTube 16:9")
    plan_niche = st.text_input("Content niche / topic",
                               placeholder="e.g. fitness tips, car reviews")
    plan_angle = st.text_input(
        "Creator commentary / angle",
        placeholder="e.g. I explain the mistake beginners make here")
    if st.button("🗂️ Generate plan"):
        if not rights:
            st.warning("Please complete the rights declaration first.")
        elif not source_note.strip():
            st.warning("Please add a source note first.")
        elif not plan_platform.strip():
            st.warning("Please add the target platform & format first.")
        else:
            try:
                with st.spinner("Building your transformation plan…"):
                    from src.planner import build_plan
                    plan = build_plan(
                        metadata={"source": sp_source["source"]
                                  if sp_source else "",
                                  "clip_length_seconds": clip_len,
                                  "reframe": ui_config["reframe"]
                                  ["params"].get("mode", "blur")},
                        platform_format=plan_platform, niche=plan_niche,
                        creator_angle=plan_angle, rights=rights,
                        source_note=source_note)
                    plan["target_duration_seconds"] = clip_len
                    plan["scene_count"] = num_clips
                st.success("Transformation plan ready:")
                st.info(f"⚠️ {plan['risk_note']}")
                for step in plan["steps"]:
                    st.markdown(f"**{step['order']}. {step['stage']}**")
                    st.json(step)
                st.download_button(
                    "⬇️ Download plan (.json)",
                    json.dumps(plan, indent=2),
                    file_name="transformation-plan.json",
                    key="dl-plan")
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

# ---------------------------------------------------------------------------
# Tab 5 — Master Prompt (lock a template once; Step 2 generates by topic)
# ---------------------------------------------------------------------------
with tab_master:
    from src import generators, master_prompt
    from src.schemas import MasterPromptTemplate

    st.subheader("Master Prompt — lock your production template")
    st.caption("Set everything once — characters, style, structure and "
               "posting defaults. Generation — niche se master prompt, "
               "aur topic se poora pack — ✍️ Content Studio tab mein "
               "hota hai; yahan templates lock hote hain aur saved "
               "packs mehfooz rehte hain.")

    _notice = st.session_state.pop("mp_notice", None)
    if _notice:
        st.success(_notice)

    NEW_TEMPLATE = "➕ New template"
    MP_FORMATS = ["Shorts 30s", "Reel 60s", "YouTube 3–5 min"]
    MP_LANGUAGES = ["English", "Urdu", "Roman Urdu"]

    template_names = master_prompt.list_names()
    if template_names:
        for _tname in template_names:
            st.markdown(f"**{_tname}** — "
                        f"{master_prompt.count_topics(_tname)} topics")
        st.divider()
    choice = st.selectbox("Template", [NEW_TEMPLATE] + template_names,
                          key="mp_choice")

    # When the selection changes, load that template's saved values
    # into the form fields (blank defaults for a new template).
    if st.session_state.get("mp_loaded_for") != choice:
        loaded_tpl = (master_prompt.load(choice)
                      if choice != NEW_TEMPLATE else None)
        vals = loaded_tpl or MasterPromptTemplate(name="")
        st.session_state["mp_name"] = vals.name
        st.session_state["mp_characters"] = master_prompt.format_characters(
            [c.model_dump() for c in vals.characters])
        st.session_state["mp_visual_style"] = vals.visual_style
        st.session_state["mp_negative"] = vals.negative_prompt
        st.session_state["mp_format"] = (
            vals.target_format if vals.target_format in MP_FORMATS
            else "Reel 60s")
        st.session_state["mp_beats"] = int(vals.beat_count)
        st.session_state["mp_hook"] = vals.hook_style
        st.session_state["mp_cta"] = vals.cta
        st.session_state["mp_language"] = (
            vals.language if vals.language in MP_LANGUAGES else "English")
        st.session_state["mp_tone"] = vals.tone
        st.session_state["mp_caption"] = vals.caption_style
        st.session_state["mp_hashtags"] = vals.hashtags
        st.session_state["mp_loaded_for"] = choice

    tpl_name = st.text_input("Template name", key="mp_name",
                             placeholder="e.g. Paws & Plates — Restaurant Cats")
    tpl_characters = st.text_area(
        "Characters", key="mp_characters", height=110,
        help="One character per line as “Name — description”, e.g. "
             "“Gus — fluffy orange tabby, green eyes, restaurant manager”. "
             "These exact descriptions go into every visual prompt, so "
             "your characters stay the same in every video.")
    tpl_visual_style = st.text_area(
        "Visual style", key="mp_visual_style", height=80,
        help="The fixed look of every scene, e.g. “cinematic realistic, "
             "warm light, cozy American diner, vertical 9:16”.")
    tpl_negative = st.text_area(
        "Negative prompt", key="mp_negative", height=70,
        help="What must never appear in a generated scene.")
    col_f, col_b = st.columns(2)
    with col_f:
        tpl_format = st.selectbox("Target format", MP_FORMATS,
                                  key="mp_format")
    with col_b:
        tpl_beats = st.number_input("Beat count", min_value=0, max_value=30,
                                    step=1, key="mp_beats",
                                    help="0 = auto — the generator decides "
                                         "from the format.")
    tpl_hook = st.text_input("Hook style", key="mp_hook",
                             help="How every video should open, e.g. "
                                  "“bold question in the first 3 seconds”.")
    tpl_cta = st.text_input("CTA line", key="mp_cta",
                            help="The fixed closing call-to-action line.")
    col_l, col_t = st.columns(2)
    with col_l:
        tpl_language = st.selectbox("Language", MP_LANGUAGES,
                                    key="mp_language")
    with col_t:
        tpl_tone = st.text_input("Tone", key="mp_tone")
    tpl_caption = st.text_area("Caption style", key="mp_caption", height=70,
                               help="How posting captions should be written.")
    tpl_hashtags = st.text_input("Hashtags", key="mp_hashtags",
                                 help="The fixed hashtag set for every post.")

    if st.button("🔒 Save / Lock template", type="primary"):
        clean_name = (tpl_name or "").strip()
        if not clean_name:
            st.error("Give the template a name first — a locked template "
                     "is saved and picked by its name.")
        else:
            master_prompt.save(MasterPromptTemplate(
                name=clean_name,
                characters=master_prompt.parse_characters(tpl_characters),
                visual_style=tpl_visual_style,
                negative_prompt=tpl_negative,
                target_format=tpl_format,
                beat_count=int(tpl_beats),
                hook_style=tpl_hook,
                cta=tpl_cta,
                language=tpl_language,
                tone=tpl_tone,
                caption_style=tpl_caption,
                hashtags=tpl_hashtags))
            st.session_state["mp_last_saved"] = clean_name
            st.success(f"🔒 Locked — “{clean_name}” is saved. From now on "
                       "it can drive generation with just a topic name.")

    # What's locked — always re-read from storage, so it proves the
    # template really persisted (not just what's in the form).
    summary_name = (choice if choice != NEW_TEMPLATE
                    else st.session_state.get("mp_last_saved", ""))
    saved_tpl = master_prompt.load(summary_name) if summary_name else None
    if saved_tpl is not None:
        st.divider()
        st.markdown("#### 🔒 What's locked")
        st.markdown(f"**Template:** {saved_tpl.name}")
        char_names = ", ".join(c.name for c in saved_tpl.characters) or "—"
        st.markdown(f"**Characters:** {char_names}")
        st.markdown(
            f"**Format:** {saved_tpl.target_format} · "
            f"**Beats:** {saved_tpl.beat_count or 'Auto'} · "
            f"**Language:** {saved_tpl.language}")
        if saved_tpl.cta:
            st.markdown(f"**CTA:** {saved_tpl.cta}")

    if choice != NEW_TEMPLATE:
        st.divider()
        if st.checkbox("Delete this template", key=f"mp_del_{choice}"):
            if st.button("🗑️ Delete", key="mp_delete_btn"):
                master_prompt.delete(choice)
                st.session_state["mp_notice"] = (
                    f"Deleted template “{choice}”.")
                st.session_state.pop("mp_loaded_for", None)
                st.rerun()

    # ------------------------------------------------------------------
    # Topics — the selected template's own section. A topic lives under
    # exactly one template and is never mixed with another's. Packs are
    # generated in the Content Studio tab and auto-save onto their
    # topic; here they stay viewable, in order, under their template.
    # ------------------------------------------------------------------
    if choice != NEW_TEMPLATE:
        st.divider()
        topic_total = master_prompt.count_topics(choice)
        st.subheader(f"📌 Topics — {choice} ({topic_total})")

        topic_query = st.text_input(
            "Search topics", key=f"mp_topic_search_{choice}",
            placeholder="Type to filter this template's topics…")
        col_new, col_add = st.columns([4, 1])
        with col_new:
            new_topic = st.text_input(
                "New topic", key=f"mp_topic_new_{choice}",
                placeholder="e.g. Gus tries to cook a giant pancake")
        with col_add:
            st.write("")  # align the button with the input box
            add_clicked = st.button("➕ Add topic",
                                    key=f"mp_topic_add_{choice}")
        if add_clicked:
            clean_topic = (new_topic or "").strip()
            if not clean_topic:
                st.error("Write a topic first.")
            elif master_prompt.topic_exists(choice, clean_topic):
                st.warning(f"“{clean_topic}” already exists under "
                           f"“{choice}” — topics are not duplicated.")
            else:
                master_prompt.add_topic(choice, clean_topic)
                st.session_state["mp_notice"] = (
                    f"Topic added under “{choice}”: {clean_topic}")
                st.rerun()

        TOPIC_STATUS_LABELS = {"new": "🆕 New",
                               "generated": "✅ Generated",
                               "posted": "📣 Posted"}
        topics = master_prompt.list_topics(choice)
        if topic_query:
            _q = topic_query.strip().lower()
            topics = [t for t in topics if _q in t.topic.lower()]
        if not topics:
            st.caption("No topics match your search."
                       if topic_query else
                       "No topics here yet — add the first one above.")
        for t in topics:
            _label = (f"{t.topic} · "
                      f"{TOPIC_STATUS_LABELS.get(t.status, t.status)} · "
                      f"{(t.created_at or '')[:10]}")
            with st.expander(_label):
                if t.result:
                    if (isinstance(t.result, dict)
                            and "beats" in t.result):
                        _render_pack(t.result, choice, t.topic,
                                     f"exp_{t.id}")
                    else:
                        st.json(t.result)
                _cur = t.status if t.status in TOPIC_STATUS_LABELS else "new"
                new_status = st.selectbox(
                    "Status", list(TOPIC_STATUS_LABELS),
                    index=list(TOPIC_STATUS_LABELS).index(_cur),
                    format_func=lambda s: TOPIC_STATUS_LABELS[s],
                    key=f"mp_topic_status_{t.id}")
                if st.button("Update status",
                             key=f"mp_topic_status_btn_{t.id}"):
                    master_prompt.set_topic_status(t.id, new_status)
                    st.session_state["mp_notice"] = (
                        f"Topic “{t.topic}” is now "
                        f"{TOPIC_STATUS_LABELS[new_status]}.")
                    st.rerun()
                if st.checkbox("Delete this topic",
                               key=f"mp_topic_del_{t.id}"):
                    if st.button("🗑️ Delete topic",
                                 key=f"mp_topic_del_btn_{t.id}"):
                        master_prompt.delete_topic(t.id)
                        st.session_state["mp_notice"] = (
                            f"Deleted topic “{t.topic}”.")
                        st.rerun()
