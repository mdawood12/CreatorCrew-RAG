"""framing.py — aspect-ratio reframing, zoom, PiP and overlays.

Operations: reframe (9:16 / 1:1 / 16:9, blur-pad or centre crop, plus
a face-tracked "smart" crop — Phase 5, adopted from VIRALCUT AI),
zoom (slow zoompan push-in), pip (picture-in-picture second video),
text_overlay, logo_overlay, hook (opening hook text + progress bar —
the splitter's original signature look, wired into the pipeline).
"""
from __future__ import annotations

from pathlib import Path

from ..config import logger
from . import registry
from ._util import FONT, esc_text, probe, run_ffmpeg, wrap_lines

RATIOS = {"9:16": (1080, 1920), "1:1": (1080, 1080), "16:9": (1920, 1080)}

# YuNet face model (free, OpenCV model zoo) — fetched into assets/ at
# build time. When it is missing or OpenCV is unavailable, the bundled
# Haar cascade is used; when no face is found at all, smart mode falls
# back to the classic blur-pad behaviour.
YUNET_MODEL = (Path(__file__).resolve().parent.parent.parent
               / "assets" / "face_detection_yunet_2023mar.onnx")

# Per-shot smart reframing (strengthening pass, 2026-11-23): the clip
# is sampled every SHOT_SAMPLE_INTERVAL seconds; a mean-absdiff above
# SHOT_DIFF_THRESHOLD between consecutive samples marks a shot cut
# (validated on the BBC verification clip: within-shot diffs <= ~7,
# the real cut scored 55). Faces smaller than MIN_FACE_AREA_FRAC of
# the frame are ignored — on the verification clip the illustrated
# backdrop faces measured ~0.1% of frame vs ~1% for the real
# presenters, so the area floor removes that pollution.
SHOT_SAMPLE_INTERVAL = 0.5
SHOT_DIFF_THRESHOLD = 20.0
MIN_SHOT_SECONDS = 0.6
MIN_FACE_AREA_FRAC = 0.003
_TRACK_JUMP = 0.25      # sticky-EMA guard: ignore subject switches


def _encode(out: Path) -> list[str]:
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "160k", str(out)]


def _blur_filter(w: int, h: int) -> str:
    return (f"split[a][b];"
            f"[a]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},gblur=sigma=40[bg];"
            f"[b]scale={w}:-2[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1")


def reframe(in_path: Path, params: dict, ctx: dict) -> Path:
    w, h = RATIOS[params["ratio"]]
    if params["mode"] == "smart":
        return _reframe_smart(in_path, params, ctx, w, h)
    if params["mode"] == "crop":
        vf = (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
              f"crop={w}:{h},setsar=1")
    else:  # blur-pad: blurred full-frame background + fitted foreground
        vf = _blur_filter(w, h)
    out = ctx["workdir"] / f"{in_path.stem}_reframe.mp4"
    run_ffmpeg(["-i", str(in_path), "-vf", vf, *_encode(out)])
    return out


# ---------------------------------------------------------------------------
# Face-track smart reframing (Phase 5 — VIRALCUT Stage 5)
# ---------------------------------------------------------------------------
def _load_detector(width: int, height: int):
    """Return (kind, find_faces) where kind is "yunet", "haar" or
    "none" and find_faces(frame) -> [(cx, cy), ...] in pixels."""
    try:
        import cv2
    except Exception:
        return "none", None
    if YUNET_MODEL.exists():
        try:
            det = cv2.FaceDetectorYN.create(
                str(YUNET_MODEL), "", (width, height), 0.6)

            def find_yunet(frame):
                det.setInputSize((frame.shape[1], frame.shape[0]))
                _ok, faces = det.detect(frame)
                if faces is None:
                    return []
                return [(float(f[0]) + float(f[2]) / 2.0,
                         float(f[1]) + float(f[3]) / 2.0) for f in faces]
            return "yunet", find_yunet
        except Exception as e:
            logger.warning("YuNet detector failed to load (%s); "
                           "falling back to Haar", e)
    try:
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        if not cascade.empty():

            def find_haar(frame):
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                boxes = cascade.detectMultiScale(gray, 1.1, 4)
                return [(float(x) + float(bw) / 2.0,
                         float(y) + float(bh) / 2.0)
                        for (x, y, bw, bh) in boxes]
            return "haar", find_haar
    except Exception as e:
        logger.warning("Haar detector failed to load: %s", e)
    return "none", None


def _load_face_boxes(width: int, height: int):
    """Return (kind, find_boxes) where find_boxes(frame) -> list of
    {"cx", "cy", "area", "conf"} in pixels / frame fraction, sorted
    largest-first, with faces below MIN_FACE_AREA_FRAC of the frame
    filtered out (backdrop illustrations, poster faces). Haar boxes
    carry conf 1.0 (the cascade reports no score)."""
    try:
        import cv2
    except Exception:
        return "none", None
    frame_area = float(width * height)
    if YUNET_MODEL.exists():
        try:
            det = cv2.FaceDetectorYN.create(
                str(YUNET_MODEL), "", (width, height), 0.6)

            def find_yunet_boxes(frame):
                det.setInputSize((frame.shape[1], frame.shape[0]))
                _ok, faces = det.detect(frame)
                if faces is None:
                    return []
                boxes = []
                for f in faces:
                    area = float(f[2]) * float(f[3]) / frame_area
                    if area < MIN_FACE_AREA_FRAC:
                        continue
                    boxes.append({
                        "cx": float(f[0]) + float(f[2]) / 2.0,
                        "cy": float(f[1]) + float(f[3]) / 2.0,
                        "area": area, "conf": float(f[14])})
                boxes.sort(key=lambda b: b["area"], reverse=True)
                return boxes
            return "yunet", find_yunet_boxes
        except Exception as e:
            logger.warning("YuNet detector failed to load (%s); "
                           "falling back to Haar", e)
    try:
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        if not cascade.empty():

            def find_haar_boxes(frame):
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                boxes = []
                for (x, y, bw, bh) in cascade.detectMultiScale(gray, 1.1, 4):
                    area = float(bw) * float(bh) / frame_area
                    if area < MIN_FACE_AREA_FRAC:
                        continue
                    boxes.append({"cx": float(x) + float(bw) / 2.0,
                                  "cy": float(y) + float(bh) / 2.0,
                                  "area": area, "conf": 1.0})
                boxes.sort(key=lambda b: b["area"], reverse=True)
                return boxes
            return "haar", find_haar_boxes
    except Exception as e:
        logger.warning("Haar detector failed to load: %s", e)
    return "none", None


def analyse_shots(video_path: str | Path,
                  sample_interval: float = SHOT_SAMPLE_INTERVAL) -> dict:
    """Split the clip into shots and find the face centre of each.

    Frames are sampled every `sample_interval` seconds; a large
    frame-difference between consecutive samples marks a shot cut.
    Within a shot the largest face per sample is tracked with the
    same EMA + deadband smoothing as detect_face_track, plus a jump
    guard so a second presenter entering the picks cannot drag the
    track away from the shot's subject.

    Returns {"detector": ..., "duration": float, "shots": [{"start",
    "end", "centre": (nx, ny) | None, "faces": samples with a face,
    "samples": int}, ...]}. A shot's centre is None when no usable
    face was seen in it (caller falls back to blur-pad for it)."""
    result: dict = {"detector": "none", "duration": 0.0, "shots": []}
    try:
        import cv2
        import numpy as np
    except Exception:
        return result
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return result
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if total <= 0 or fps <= 0 or width <= 0 or height <= 0:
            return result
        duration = total / fps
        result["duration"] = duration
        kind, find_boxes = _load_face_boxes(width, height)
        result["detector"] = kind

        samples: list[dict] = []        # {"t", "diff", "centre"|None}
        prev_thumb = None
        t = sample_interval / 2.0
        while t < duration:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if ok and frame is not None:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                thumb = cv2.resize(gray, (96, 54)).astype("float32")
                diff = 0.0
                if prev_thumb is not None:
                    diff = float(np.mean(np.abs(thumb - prev_thumb)))
                prev_thumb = thumb
                centre = None
                if find_boxes is not None:
                    boxes = find_boxes(frame)
                    if boxes:
                        centre = (boxes[0]["cx"] / width,
                                  boxes[0]["cy"] / height)
                samples.append({"t": t, "diff": diff, "centre": centre})
            t += sample_interval
        if not samples:
            return result

        # Shot boundaries at the midpoint before each high-diff sample.
        groups: list[list[dict]] = [[samples[0]]]
        bounds: list[float] = []
        for prev, cur in zip(samples, samples[1:]):
            if cur["diff"] > SHOT_DIFF_THRESHOLD:
                bounds.append((prev["t"] + cur["t"]) / 2.0)
                groups.append([cur])
            else:
                groups[-1].append(cur)
        starts = [0.0] + bounds
        ends = bounds + [duration]
        shots = [{"start": s, "end": e, "group": g}
                 for s, e, g in zip(starts, ends, groups)]

        # Merge blink-length shots into a neighbour so the concat
        # never has to carry a sub-second sliver.
        merged: list[dict] = []
        for shot in shots:
            if merged and shot["end"] - shot["start"] < MIN_SHOT_SECONDS:
                merged[-1]["end"] = shot["end"]
                merged[-1]["group"] += shot["group"]
            else:
                merged.append(shot)
        if len(merged) > 1 and \
                merged[0]["end"] - merged[0]["start"] < MIN_SHOT_SECONDS:
            merged[1]["group"] = merged[0]["group"] + merged[1]["group"]
            merged[1]["start"] = merged[0]["start"]
            merged.pop(0)

        alpha, deadband = 0.35, 0.02     # same damping as the tracker
        out_shots = []
        for shot in merged:
            smoothed: tuple[float, float] | None = None
            path: list[tuple[float, float]] = []
            faces = 0
            for smp in shot["group"]:
                point = smp["centre"]
                if point is None:
                    continue
                faces += 1
                if smoothed is None:
                    smoothed = point
                else:
                    dx = point[0] - smoothed[0]
                    dy = point[1] - smoothed[1]
                    if abs(dx) > _TRACK_JUMP or abs(dy) > _TRACK_JUMP:
                        continue        # a different subject — stay
                    if abs(dx) >= deadband or abs(dy) >= deadband:
                        smoothed = (smoothed[0] + alpha * dx,
                                    smoothed[1] + alpha * dy)
                path.append(smoothed)
            centre = None
            if path:
                centre = (sum(p[0] for p in path) / len(path),
                          sum(p[1] for p in path) / len(path))
            out_shots.append({"start": round(shot["start"], 3),
                              "end": round(shot["end"], 3),
                              "centre": centre, "faces": faces,
                              "samples": len(shot["group"])})
        result["shots"] = out_shots
        return result
    finally:
        cap.release()


def detect_face_track(video_path: str | Path, samples: int = 12) -> dict:
    """Sample frames across the clip, detect the face centre in each,
    and smooth the centre path with EMA + deadband damping (VIRALCUT
    Stage 5) so the crop window never jitters.

    Returns {"detector": "yunet"|"haar"|"none", "samples": int,
    "faces": int (samples with a face), "path": [(nx, ny), ...]
    smoothed normalised centres, "centre": (nx, ny) mean of the
    smoothed path, or None when no face was found}."""
    result = {"detector": "none", "samples": 0, "faces": 0,
              "path": [], "centre": None}
    try:
        import cv2
    except Exception:
        return result
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return result
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if total <= 0 or width <= 0 or height <= 0:
            return result
        kind, find = _load_detector(width, height)
        result["detector"] = kind
        if find is None:
            return result
        alpha, deadband = 0.35, 0.02     # EMA factor; ~2% of frame
        smoothed: tuple[float, float] | None = None
        path: list[tuple[float, float]] = []
        found = 0
        idxs = [int(total * (i + 0.5) / samples) for i in range(samples)]
        for idx in idxs:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            result["samples"] += 1
            if not ok or frame is None:
                continue
            faces = find(frame)
            if not faces:
                continue
            found += 1
            cx, cy = faces[0]
            point = (cx / width, cy / height)
            if smoothed is None:
                smoothed = point
            else:
                dx, dy = point[0] - smoothed[0], point[1] - smoothed[1]
                if abs(dx) >= deadband or abs(dy) >= deadband:
                    smoothed = (smoothed[0] + alpha * dx,
                                smoothed[1] + alpha * dy)
            path.append(smoothed)
        result["faces"] = found
        result["path"] = path
        if path:
            result["centre"] = (sum(p[0] for p in path) / len(path),
                                sum(p[1] for p in path) / len(path))
        return result
    finally:
        cap.release()


def _crop_vf(centre: tuple[float, float], sw: int, sh: int,
             w: int, h: int) -> str:
    """Crop filter centred on a normalised face centre, clamped to
    the frame, scaled to the target size."""
    target_ratio = w / h
    crop_w = min(sw, int(sh * target_ratio))
    crop_h = int(crop_w / target_ratio)
    if crop_h > sh:
        crop_h = sh
        crop_w = int(sh * target_ratio)
    cx, cy = centre
    x = int(min(max(cx * sw - crop_w / 2, 0), max(sw - crop_w, 0)))
    y = int(min(max(cy * sh - crop_h / 2, 0), max(sh - crop_h, 0)))
    return f"crop={crop_w}:{crop_h}:{x}:{y},scale={w}:{h},setsar=1"


def _reframe_smart(in_path: Path, params: dict, ctx: dict,
                   w: int, h: int) -> Path:
    """Per-shot smart reframe: one face-tracked crop per shot, so a
    shot change can move the crop to the new speaker (the pre-fix
    design used a single static crop for the whole clip and lost the
    subject at the first cut). Shots without a usable face fall back
    to blur-pad for that shot only."""
    out = ctx["workdir"] / f"{in_path.stem}_reframe.mp4"
    info = probe(in_path)
    sw, sh = info["width"], info["height"]
    analysis = analyse_shots(in_path)
    shots = analysis["shots"]
    if not shots or all(s["centre"] is None for s in shots):
        logger.info("Smart reframe: detector=%s — no face found in "
                    "any shot, using blur-pad fallback",
                    analysis["detector"])
        run_ffmpeg(["-i", str(in_path), "-vf", _blur_filter(w, h),
                    *_encode(out)])
        return out
    if len(shots) == 1:
        centre = shots[0]["centre"]
        logger.info("Smart reframe: single shot, detector=%s faces="
                    "%d/%d centre=(%.2f, %.2f)", analysis["detector"],
                    shots[0]["faces"], shots[0]["samples"],
                    centre[0], centre[1])
        run_ffmpeg(["-i", str(in_path), "-vf",
                    _crop_vf(centre, sw, sh, w, h), *_encode(out)])
        return out
    logger.info("Smart reframe: %d shots detected (detector=%s): %s",
                len(shots), analysis["detector"],
                [(s["start"], s["end"],
                  None if s["centre"] is None else
                  (round(s["centre"][0], 2), round(s["centre"][1], 2)))
                 for s in shots])
    parts = []
    for i, shot in enumerate(shots):
        part = ctx["workdir"] / f"{in_path.stem}_shot{i:02d}.mp4"
        vf = (_crop_vf(shot["centre"], sw, sh, w, h)
              if shot["centre"] is not None else _blur_filter(w, h))
        run_ffmpeg(["-ss", f"{shot['start']:.3f}", "-i", str(in_path),
                    "-t", f"{shot['end'] - shot['start']:.3f}",
                    "-vf", vf, *_encode(part)])
        parts.append(part)
    listfile = ctx["workdir"] / f"{in_path.stem}_shots.txt"
    listfile.write_text("".join(f"file '{p}'\n" for p in parts),
                        encoding="utf-8")
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listfile),
                *_encode(out)])
    return out


def zoom(in_path: Path, params: dict, ctx: dict) -> Path:
    info = probe(in_path)
    w, h, fps = info["width"], info["height"], info["fps"] or 30.0
    frames = max(int(info["duration"] * fps), 1)
    amount = float(params["amount"])
    # Pre-scale 2x so zoompan has pixels to work with, then slow push-in.
    # d=1 is essential for VIDEO input: zoompan's d is frames-per-input-
    # frame, so d>1 would multiply the clip length by d.
    vf = (f"scale={w * 2}:{h * 2},"
          f"zoompan=z='1+{amount:.3f}*on/{frames}':d=1:"
          f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps:.3f},"
          "setsar=1")
    out = ctx["workdir"] / f"{in_path.stem}_zoom.mp4"
    run_ffmpeg(["-i", str(in_path), "-vf", vf, *_encode(out)])
    return out


def pip(in_path: Path, params: dict, ctx: dict) -> Path:
    pip_path = ctx.get("extras", {}).get("pip_path") or params.get("pip_path")
    if not pip_path or not Path(pip_path).exists():
        raise ValueError("Picture-in-picture needs a second video — "
                         "add one in the editing panel.")
    info = probe(in_path)
    pw = int(info["width"] * float(params["width_pct"]) / 100)
    pos = {"bottom-right": "W-w-24:H-h-24", "bottom-left": "24:H-h-24",
           "top-right": "W-w-24:24", "top-left": "24:24"}[params["position"]]
    graph = f"[1:v]scale={pw}:-2[pip];[0:v][pip]overlay={pos}"
    out = ctx["workdir"] / f"{in_path.stem}_pip.mp4"
    run_ffmpeg(["-i", str(in_path), "-i", str(pip_path),
                "-filter_complex", graph, "-map", "0:a?",
                *_encode(out)])
    return out


def text_overlay(in_path: Path, params: dict, ctx: dict) -> Path:
    text = (params.get("text") or "").strip()
    if not text:
        raise ValueError("Text overlay needs some text.")
    y = {"top": "60", "middle": "(h-text_h)/2", "bottom": "h-140"}[params["position"]]
    vf = (f"drawtext=fontfile={FONT}:text='{esc_text(text)}':"
          f"fontsize={int(params['size'])}:fontcolor=white:borderw=3:"
          f"bordercolor=black:x=(w-text_w)/2:y={y}:box=1:"
          "boxcolor=black@0.45:boxborderw=12")
    out = ctx["workdir"] / f"{in_path.stem}_text.mp4"
    run_ffmpeg(["-i", str(in_path), "-vf", vf, *_encode(out)])
    return out


def logo_overlay(in_path: Path, params: dict, ctx: dict) -> Path:
    logo = ctx.get("extras", {}).get("logo_path") or params.get("logo_path")
    if not logo or not Path(logo).exists():
        raise ValueError("Logo overlay needs a logo image — "
                         "add one in the editing panel.")
    info = probe(in_path)
    lw = int(info["width"] * float(params["width_pct"]) / 100)
    pos = {"top-right": "W-w-20:20", "top-left": "20:20",
           "bottom-right": "W-w-20:H-h-20", "bottom-left": "20:H-h-20"
           }[params["position"]]
    graph = f"[1:v]scale={lw}:-2[logo];[0:v][logo]overlay={pos}"
    out = ctx["workdir"] / f"{in_path.stem}_logo.mp4"
    run_ffmpeg(["-i", str(in_path), "-i", str(logo),
                "-filter_complex", graph, "-map", "0:a?",
                *_encode(out)])
    return out


def hook(in_path: Path, params: dict, ctx: dict) -> Path:
    text = (ctx.get("extras", {}).get("hook_text")
            or params.get("text") or "").strip()
    if not text:
        return in_path
    info = probe(in_path)
    dur = max(info["duration"], 0.1)
    vf = ""
    for i, line in enumerate(wrap_lines(text)):
        vf += (f"drawtext=fontfile={FONT}:text='{esc_text(line)}':"
               "fontsize=42:fontcolor=white:borderw=3:bordercolor=black:"
               f"x=(w-text_w)/2:y={70 + i * 58}:box=1:"
               "boxcolor=black@0.45:boxborderw=12,")
    if params.get("progress_bar", True):
        vf += (f"drawbox=x=0:y=ih-12:w='iw*t/{dur:.2f}':h=12:"
               "color=red@0.9:t=fill,")
    out = ctx["workdir"] / f"{in_path.stem}_hook.mp4"
    run_ffmpeg(["-i", str(in_path), "-vf", vf.rstrip(","), *_encode(out)])
    return out


_RATIO = {"key": "ratio", "type": "select", "default": "9:16",
          "choices": list(RATIOS), "label": "Aspect ratio",
          "help": "9:16 for Shorts/Reels, 1:1 square, 16:9 landscape."}
_MODE = {"key": "mode", "type": "select", "default": "blur",
         "choices": ["blur", "crop", "smart"], "label": "Framing mode",
         "help": "Blurred background keeps the whole picture; "
                "centre crop fills the frame; smart follows the "
                "speaker's face (falls back to blurred background "
                "when no face is found)."}
_CORNERS = ["bottom-right", "bottom-left", "top-right", "top-left"]

registry.register(registry.Operation(
    id="reframe", stage="framing", phase="A", label="Reframe (aspect ratio)",
    help="Fits the clip into the target aspect ratio.",
    func=reframe, params=[_RATIO, _MODE]))
registry.register(registry.Operation(
    id="zoom", stage="framing", phase="A", label="Slow zoom",
    help="A gentle push-in zoom across the whole clip (Ken Burns style).",
    func=zoom, params=[
        {"key": "amount", "type": "float", "default": 0.12, "min": 0.03,
         "max": 0.35, "step": 0.01, "label": "Zoom amount",
         "help": "How far the picture pushes in by the end of the clip."}]))
registry.register(registry.Operation(
    id="pip", stage="overlays", phase="A", label="Picture-in-picture",
    help="Places a second video (e.g. your face-cam) in a corner.",
    func=pip, params=[
        {"key": "width_pct", "type": "float", "default": 28.0, "min": 10.0,
         "max": 60.0, "step": 1.0, "label": "PiP width (% of frame)",
         "help": "Size of the inset video."},
        {"key": "position", "type": "select", "default": "bottom-right",
         "choices": _CORNERS, "label": "PiP corner", "help": "Which corner."},
        {"key": "pip_path", "type": "text", "default": "", "label": "PiP video path",
         "help": "Filled automatically when you add a PiP video in the panel."}]))
registry.register(registry.Operation(
    id="text_overlay", stage="overlays", phase="A", label="Text overlay",
    help="Adds a line of text over the video.",
    func=text_overlay, params=[
        {"key": "text", "type": "text", "default": "", "label": "Text",
         "help": "The words to show on screen."},
        {"key": "size", "type": "int", "default": 48, "min": 20, "max": 120,
         "step": 2, "label": "Text size", "help": "Font size in pixels."},
        {"key": "position", "type": "select", "default": "bottom",
         "choices": ["top", "middle", "bottom"], "label": "Text position",
         "help": "Where the text sits."}]))
registry.register(registry.Operation(
    id="logo_overlay", stage="overlays", phase="A", label="Logo overlay",
    help="Places your logo image in a corner of the frame.",
    func=logo_overlay, params=[
        {"key": "width_pct", "type": "float", "default": 12.0, "min": 4.0,
         "max": 40.0, "step": 1.0, "label": "Logo width (% of frame)",
         "help": "Size of the logo."},
        {"key": "position", "type": "select", "default": "top-right",
         "choices": _CORNERS, "label": "Logo corner", "help": "Which corner."},
        {"key": "logo_path", "type": "text", "default": "", "label": "Logo image path",
         "help": "Filled automatically when you add a logo in the panel."}]))
registry.register(registry.Operation(
    id="hook", stage="overlays", phase="A", label="Hook overlay",
    help="Burns the clip's opening hook text (and progress bar) on screen.",
    func=hook, params=[
        {"key": "progress_bar", "type": "bool", "default": True,
         "label": "Progress bar", "help": "Thin red bar showing watch progress."},
        {"key": "text", "type": "text", "default": "", "label": "Hook text override",
         "help": "Leave empty to use the clip's detected hook line."}]))
