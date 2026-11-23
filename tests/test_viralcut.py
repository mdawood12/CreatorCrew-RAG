"""
tests/test_viralcut.py — Phase 5 (VIRALCUT merge) verification.

Covers: 7-dimension virality scoring + >35% dedup, karaoke ASS
highlighting, the Whisper DTW-failure fallback (monkeypatched) with
synthetic word timings + the unchanged clean path, and face-track
smart reframing (YuNet/Haar detection on a moving-face fixture;
honest no-face fallback on the rights-clean test video, which is a
synthetic test pattern and contains no face).

Strengthening pass (2026-11-23) adds: karaoke events extending to
the next word's start (no caption gaps), base as the default Whisper
model, and per-shot smart reframing (shot-cut detection + one crop
per shot, proven on a synthetic two-shot fixture).

Run:  .venv/bin/python -m pytest tests/test_viralcut.py -q
"""
import subprocess
import sys
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, tools                       # noqa: E402
from src.editing import captions as cap_mod         # noqa: E402
from src.editing import framing, pipeline, scoring  # noqa: E402
from src.editing._util import probe                 # noqa: E402

TEST_VIDEO = Path.home() / "workspace/your_files/viral-clip-tool/test/source-test.mp4"
WORK = config.BASE_DIR / ".tmp" / "viralcut-test"
LENA_URL = ("https://github.com/opencv/opencv/raw/4.x/"
            "samples/data/lena.jpg")


# ---------------------------------------------------------------------------
# 1. Virality scoring
# ---------------------------------------------------------------------------
SEGMENTS = [
    {"text": "Welcome back to the channel everyone.", "start": 0.0,
     "duration": 4.0},
    {"text": "Why do 90 percent of beginners make this one mistake?",
     "start": 4.0, "duration": 4.0},
    {"text": "Nobody tells you the secret, but here is the truth!",
     "start": 8.0, "duration": 4.0},
    {"text": "First, stop doing everything the hard way.",
     "start": 12.0, "duration": 3.5},
    {"text": "So finally you get the result you wanted.",
     "start": 15.5, "duration": 3.5},
    {"text": "Um, and then some other stuff happens here slowly.",
     "start": 30.0, "duration": 6.0},
]


def test_scoring_returns_range_breakdown_and_rationale():
    ranked = scoring.rank_candidates(
        [{"start_sec": 4.0, "end_sec": 19.0},
         {"start_sec": 30.0, "end_sec": 36.0}], SEGMENTS)
    assert len(ranked) == 2
    for r in ranked:
        assert 0.0 <= r["score"] <= 100.0
        assert set(r["breakdown"]) == set(scoring.DIMENSIONS)
        assert all(0.0 <= v <= 100.0 for v in r["breakdown"].values())
        assert r["rationale"]
    # The hook-rich window must outscore the filler window.
    assert ranked[0]["start_sec"] == 4.0


def test_scoring_dedup_drops_over_35_percent_overlap():
    ranked = scoring.rank_candidates(
        [{"start_sec": 4.0, "end_sec": 19.0},
         {"start_sec": 5.0, "end_sec": 19.5},      # ~93% overlap
         {"start_sec": 30.0, "end_sec": 36.0}], SEGMENTS)
    starts = [r["start_sec"] for r in ranked]
    assert 30.0 in starts and len(ranked) == 2
    assert not (4.0 in starts and 5.0 in starts)


def test_score_window_duration_fit_peaks_near_targets():
    text = "Why does this always work? Because the reason is simple."
    near = scoring.score_window(text, 15.0)
    off = scoring.score_window(text, 47.0)
    assert near["breakdown"]["retention_fit"] > \
        off["breakdown"]["retention_fit"]


# ---------------------------------------------------------------------------
# 2. Karaoke captions
# ---------------------------------------------------------------------------
def test_karaoke_ass_highlights_active_word():
    words = [{"text": t, "start": i * 0.5, "end": i * 0.5 + 0.45}
             for i, t in enumerate(
                 ["Why", "do", "beginners", "fail?", "The", "secret",
                  "is", "simple."])]
    chunks = cap_mod._chunks(words)
    ass = cap_mod._build_ass_karaoke(chunks, {"secret"}, 52, 1080, 1920)
    assert "&H0000FFFF&" in ass                    # yellow active word
    assert "&H00FFFF00&" in ass                    # cyan keyword
    dialogues = [ln for ln in ass.splitlines()
                 if ln.startswith("Dialogue:")]
    assert len(dialogues) == len(words)            # one event per word
    # Default style is untouched by the karaoke builder.
    plain = cap_mod._build_ass(chunks, set(), 52, 1080, 1920)
    assert len([ln for ln in plain.splitlines()
                if ln.startswith("Dialogue:")]) == len(chunks)


def _ass_seconds(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def test_karaoke_events_extend_to_next_word_start():
    """No no-caption gaps: each karaoke event ends exactly when the
    next word's event begins (strengthening pass, 2026-11-23)."""
    words = [{"text": t, "start": i * 0.5, "end": i * 0.5 + 0.3}
             for i, t in enumerate(["one", "two", "three", "four",
                                    "five"])]
    chunks = cap_mod._chunks(words)
    assert len(chunks) == 1
    ass = cap_mod._build_ass_karaoke(chunks, set(), 52, 1080, 1920)
    events = []
    for ln in ass.splitlines():
        if ln.startswith("Dialogue:"):
            fields = ln.split(",", 9)
            events.append((_ass_seconds(fields[1]),
                           _ass_seconds(fields[2])))
    assert len(events) == len(words)
    for i in range(len(events) - 1):
        assert abs(events[i][1] - events[i + 1][0]) < 0.011
    # The last word keeps its own end (capped at the chunk end).
    assert abs(events[-1][1] - words[-1]["end"]) < 0.011


def test_whisper_default_model_is_base():
    """Base is the default speech engine (tiny mis-heard key
    vocabulary in the 2026-11-23 real-world verification)."""
    assert config.WHISPER_MODEL == "base"


# ---------------------------------------------------------------------------
# 3. Whisper robustness (Rule 2)
# ---------------------------------------------------------------------------
class _FakeSeg:
    def __init__(self, text, start, end, words=None):
        self.text, self.start, self.end, self.words = text, start, end, words


def _fake_model_class(segments, fail_with_words):
    class FakeModel:
        def __init__(self, *a, **k):
            pass

        def transcribe(self, src, beam_size=1, word_timestamps=False):
            if word_timestamps and fail_with_words:
                raise RuntimeError("DTW alignment failed (forced)")
            return iter(segments), SimpleNamespace(language="en")
    return FakeModel


def test_whisper_fallback_synthesizes_word_timings(monkeypatch):
    import faster_whisper
    segs = [_FakeSeg("hello brave new world", 10.0, 14.0, words=None)]
    monkeypatch.setattr(faster_whisper, "WhisperModel",
                        _fake_model_class(segs, fail_with_words=True))
    out = tools.transcript_via_whisper("ignored-local.wav")
    assert out and len(out) == 1
    words = out[0]["words"]
    assert [w["text"] for w in words] == ["hello", "brave", "new",
                                          "world"]
    starts = [w["start"] for w in words]
    assert starts == sorted(starts)                       # monotonic
    assert words[0]["start"] >= 10.0
    assert words[-1]["end"] <= 14.0 + 0.01                # within segment
    # Synthesized timings must be honestly flagged as approximate.
    assert out[0].get("words_approximate") is True
    assert all(w.get("approximate") is True for w in words)
    assert tools.word_timings_label(out) == "approximate (interpolated)"


def test_whisper_clean_path_keeps_real_word_timings(monkeypatch):
    import faster_whisper
    real = [SimpleNamespace(word=" hello", start=0.0, end=0.4),
            SimpleNamespace(word=" world", start=0.4, end=0.9),
            SimpleNamespace(word="", start=0.9, end=1.0),      # filtered
            SimpleNamespace(word=" junk", start=None, end=None)]  # filtered
    segs = [_FakeSeg("hello world", 0.0, 1.0, words=real)]
    monkeypatch.setattr(faster_whisper, "WhisperModel",
                        _fake_model_class(segs, fail_with_words=False))
    out = tools.transcript_via_whisper("ignored-local.wav")
    assert out and [w["text"] for w in out[0]["words"]] == ["hello",
                                                            "world"]
    assert out[0]["words"][1]["start"] == 0.4
    # Real timings carry no approximate flag.
    assert "words_approximate" not in out[0]
    assert all("approximate" not in w for w in out[0]["words"])
    assert tools.word_timings_label(out) == "word-level"
    assert tools.word_timings_label([{"text": "x"}]) == \
        "segment-level (no word timings)"


def test_candidate_reason_uses_honest_virality_label():
    from src.splitter import propose_candidates
    cands = propose_candidates(SEGMENTS, clip_len=15, max_clips=3)
    assert cands
    for c in cands:
        assert c.reason.startswith("Virality potential (heuristic) ")
        assert "Virality score" not in c.reason


# ---------------------------------------------------------------------------
# 4. Face-track smart reframing
# ---------------------------------------------------------------------------
def _face_fixture() -> Path:
    """A 6 s clip with a real face (OpenCV's Lena sample) sliding
    left → right across a 1280x720 frame."""
    WORK.mkdir(parents=True, exist_ok=True)
    clip = WORK / "face-move.mp4"
    if clip.exists():
        return clip
    lena = WORK / "lena.jpg"
    if not lena.exists():
        try:
            urllib.request.urlretrieve(LENA_URL, lena)
        except Exception:
            pytest.skip("face fixture image unavailable (offline)")
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "color=c=0x202020:s=1280x720:r=30:d=6",
         "-loop", "1", "-framerate", "30", "-i", str(lena),
         "-filter_complex",
         "[1:v]scale=512:512[fg];[0:v][fg]overlay=x='768*t/6':y=104[v]",
         "-map", "[v]", "-t", "6", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", str(clip)],
        capture_output=True, timeout=300, check=True)
    return clip


def test_face_track_detects_and_follows_face():
    clip = _face_fixture()
    track = framing.detect_face_track(clip)
    print(f"\nface-track: detector={track['detector']} "
          f"faces={track['faces']}/{track['samples']} "
          f"centre={track['centre']}")
    assert track["detector"] in ("yunet", "haar")
    assert track["faces"] >= 3
    xs = [p[0] for p in track["path"]]
    assert xs[-1] > xs[0] + 0.10          # path follows the moving face


def test_smart_reframe_renders_vertical_on_face_clip():
    clip = _face_fixture()
    cfg = {"reframe": {"enabled": True,
                       "params": {"ratio": "9:16", "mode": "smart"}}}
    out = WORK / "face-smart.mp4"
    res = pipeline.render_segment(clip, 0.0, 5.0, cfg, out, WORK / "wf")
    info = probe(out)
    assert "reframe" in res["applied"]
    assert (info["width"], info["height"]) == (1080, 1920)


def _two_shot_fixture() -> Path:
    """A 6 s clip with a hard cut at 3 s: the Lena face sits at the
    left for the first shot and at the right for the second — the
    case the old single static crop failed on real footage."""
    WORK.mkdir(parents=True, exist_ok=True)
    clip = WORK / "face-twoshot.mp4"
    if clip.exists():
        return clip
    lena = WORK / "lena.jpg"
    if not lena.exists():
        try:
            urllib.request.urlretrieve(LENA_URL, lena)
        except Exception:
            pytest.skip("face fixture image unavailable (offline)")
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "color=c=0x202020:s=1280x720:r=30:d=6",
         "-loop", "1", "-framerate", "30", "-i", str(lena),
         "-filter_complex",
         "[1:v]scale=512:512[fg];"
         "[0:v][fg]overlay=x='if(lt(t,3),40,728)':y=104[v]",
         "-map", "[v]", "-t", "6", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", str(clip)],
        capture_output=True, timeout=300, check=True)
    return clip


def test_shot_detection_finds_cut_and_per_shot_centres():
    clip = _two_shot_fixture()
    analysis = framing.analyse_shots(clip)
    shots = analysis["shots"]
    print(f"\ntwo-shot analysis: {[(s['start'], s['end'], s['centre']) for s in shots]}")
    assert len(shots) >= 2
    assert abs(shots[1]["start"] - 3.0) <= 0.75      # the cut is found
    assert shots[0]["centre"] and shots[0]["centre"][0] < 0.40
    assert shots[-1]["centre"] and shots[-1]["centre"][0] > 0.60


def test_smart_reframe_two_shot_keeps_face_in_both_shots():
    clip = _two_shot_fixture()
    cfg = {"reframe": {"enabled": True,
                       "params": {"ratio": "9:16", "mode": "smart"}}}
    out = WORK / "twoshot-smart.mp4"
    res = pipeline.render_segment(clip, 0.0, 6.0, cfg, out, WORK / "wt")
    info = probe(out)
    assert "reframe" in res["applied"]
    assert (info["width"], info["height"]) == (1080, 1920)
    assert abs(info["duration"] - 6.0) < 0.6
    import cv2
    _kind, find_boxes = framing._load_face_boxes(info["width"],
                                                 info["height"])
    assert find_boxes is not None
    cap = cv2.VideoCapture(str(out))
    try:
        for t in (1.5, 4.5):        # one frame inside each shot
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, frame = cap.read()
            assert ok and frame is not None
            boxes = find_boxes(frame)
            assert boxes, f"no face in reframed output at {t}s"
            cx = boxes[0]["cx"] / info["width"]
            assert 0.2 < cx < 0.8, f"face off-centre at {t}s: {cx:.2f}"
    finally:
        cap.release()


def test_smart_reframe_no_face_falls_back_on_test_video():
    assert TEST_VIDEO.exists()
    track = framing.detect_face_track(TEST_VIDEO)
    print(f"\ntest-video track: detector={track['detector']} "
          f"faces={track['faces']}/{track['samples']}")
    assert track["faces"] == 0 and track["centre"] is None
    cfg = {"reframe": {"enabled": True,
                       "params": {"ratio": "9:16", "mode": "smart"}}}
    out = WORK / "noface-smart.mp4"
    pipeline.render_segment(TEST_VIDEO, 5.0, 10.0, cfg, out, WORK / "wn")
    info = probe(out)
    assert (info["width"], info["height"]) == (1080, 1920)
