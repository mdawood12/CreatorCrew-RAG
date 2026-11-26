"""
Video length + scene count selector for the Streamlit app.

Usage in app.py:
    from video_settings import render_video_settings
    settings = render_video_settings()          # in sidebar: with st.sidebar: ...
    plan["target_duration_seconds"] = settings["duration_seconds"]
    plan["scene_count"] = settings["scene_count"]
"""
import math

# ---- Config (edit here) -------------------------------------------------
DURATION_PRESETS = list(range(45, 301, 15))        # 0:45 ... 5:00
SCENE_PRESETS = [6, 8, 10, 12, 15, 20, 24, 30, 40, 60]
CUSTOM = "Custom"
AUTO = "Auto (recommended)"
DEFAULT_SECONDS_PER_SCENE = 5
MIN_SCENE_SECONDS, MAX_SCENE_SECONDS = 2.0, 8.0    # warn outside this range
CUSTOM_DURATION_RANGE = (15, 300, 5)               # min, max, step (seconds)
CUSTOM_SCENE_RANGE = (1, 120)
WORDS_PER_MINUTE = 150
# ---- Splitter clip settings (Step 3) ------------------------------------
CLIP_DURATION_PRESETS = [10, 15, 20, 30, 45, 60, 90, 120]
CLIP_COUNT_PRESETS = [1, 2, 3, 5, 8, 10]
CUSTOM_CLIP_DURATION_RANGE = (5, 300, 5)           # min, max, step (seconds)
CUSTOM_CLIP_COUNT_RANGE = (1, 20)
# -------------------------------------------------------------------------


def fmt(seconds: int) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def auto_scene_count(duration_seconds: int) -> int:
    return max(1, math.ceil(duration_seconds / DEFAULT_SECONDS_PER_SCENE))


def compute(duration_seconds: int, scene_count: int) -> dict:
    avg = duration_seconds / scene_count
    warnings = []
    if avg > MAX_SCENE_SECONDS:
        warnings.append(f"Scenes average {avg:.1f}s. Long clips look static and most AI tools cap clips near 5-10s. Add scenes.")
    if avg < MIN_SCENE_SECONDS:
        warnings.append(f"Scenes average {avg:.1f}s. Very fast cuts are hard to follow. Reduce scenes.")
    return {
        "duration_seconds": int(duration_seconds),
        "duration_label": fmt(duration_seconds),
        "scene_count": int(scene_count),
        "avg_scene_seconds": round(avg, 1),
        "voiceover_words": round(duration_seconds / 60 * WORDS_PER_MINUTE),
        "warnings": warnings,
    }


def render_video_settings(key_prefix: str = "vs") -> dict:
    import streamlit as st  # imported here so compute() can be tested without Streamlit

    st.subheader("Video settings")

    # 1) Duration
    duration_options = [f"{fmt(s)}" for s in DURATION_PRESETS] + [CUSTOM]
    choice = st.selectbox("Video duration", duration_options, index=1, key=f"{key_prefix}_dur")
    if choice == CUSTOM:
        lo, hi, step = CUSTOM_DURATION_RANGE
        duration = st.number_input("Custom duration (seconds)", lo, hi, 90, step, key=f"{key_prefix}_dur_c")
    else:
        m, s = choice.split(":")
        duration = int(m) * 60 + int(s)

    # 2) Scenes
    scene_options = [AUTO] + [str(n) for n in SCENE_PRESETS] + [CUSTOM]
    scene_choice = st.selectbox("Number of scenes", scene_options, index=0, key=f"{key_prefix}_sc")
    if scene_choice == AUTO:
        scenes = auto_scene_count(duration)
    elif scene_choice == CUSTOM:
        lo, hi = CUSTOM_SCENE_RANGE
        scenes = st.number_input("Custom number of scenes", lo, hi, auto_scene_count(duration), 1, key=f"{key_prefix}_sc_c")
    else:
        scenes = int(scene_choice)

    result = compute(int(duration), int(scenes))

    c1, c2, c3 = st.columns(3)
    c1.metric("Scenes", result["scene_count"])
    c2.metric("Avg per scene", f'{result["avg_scene_seconds"]}s')
    c3.metric("Voiceover", f'~{result["voiceover_words"]} words')
    for w in result["warnings"]:
        st.warning(w)
    return result


def clip_label(seconds: int) -> str:
    """Human label for a clip duration: 45 -> '45 seconds',
    60 -> '1 minute', 90 -> '1 minute 30 seconds', 120 -> '2 minutes'."""
    s = int(seconds)
    if s < 60:
        return f"{s} seconds"
    m, r = divmod(s, 60)
    unit = "minute" if m == 1 else "minutes"
    if r == 0:
        return f"{m} {unit}"
    return f"{m} {unit} {r} seconds"


def render_clip_settings(key_prefix: str = "cs") -> dict:
    """Splitter Step 3 panel: clip duration + number of clips dropdowns.

    Both controls offer presets plus a Custom option (the user types
    their own value). Returns {"duration_seconds": int, "clip_count": int}.
    """
    import streamlit as st  # lazy, same pattern as render_video_settings

    with st.container(border=True):
        st.subheader("🎬 Clip settings")
        col_d, col_n = st.columns(2)

        dur_options = [clip_label(s) for s in CLIP_DURATION_PRESETS] + [CUSTOM]
        with col_d:
            dur_choice = st.selectbox(
                "Clip duration", dur_options,
                index=dur_options.index(clip_label(15)),
                key=f"{key_prefix}_clip_dur",
                help="How long each generated clip should be.")
            if dur_choice == CUSTOM:
                lo, hi, step = CUSTOM_CLIP_DURATION_RANGE
                duration = st.number_input(
                    "Custom duration (seconds)", lo, hi, 30, step,
                    key=f"{key_prefix}_clip_dur_c")
            else:
                duration = CLIP_DURATION_PRESETS[
                    dur_options.index(dur_choice)]

        count_options = [str(n) for n in CLIP_COUNT_PRESETS] + [CUSTOM]
        with col_n:
            count_choice = st.selectbox(
                "Number of clips", count_options,
                index=count_options.index("3"),
                key=f"{key_prefix}_clip_n",
                help="How many top-scoring clips to generate.")
            if count_choice == CUSTOM:
                lo, hi = CUSTOM_CLIP_COUNT_RANGE
                count = st.number_input(
                    "Custom number of clips", lo, hi, 3, 1,
                    key=f"{key_prefix}_clip_n_c")
            else:
                count = int(count_choice)

        st.caption(f"**{int(count)} clip(s)** × **~{int(duration)}s** each — "
                   "the best-scoring scenes will be picked.")
    return {"duration_seconds": int(duration), "clip_count": int(count)}
