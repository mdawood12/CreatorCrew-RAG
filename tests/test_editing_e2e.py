"""End-to-end test for the Video Input & Automated Repurposing Module.

Run:  .venv/bin/python -m tests.test_editing_e2e
Uses the rights-clean self-made test video (90 s, 1280x720, TTS speech).
Covers: intake/library, scene candidates, pipeline renders (ratios,
captions, BGM ducking + loudness + RMS scan, op smoke test) and the
splitter regression path. Prints PASS/FAIL per check; exit 1 on failure.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, tools                       # noqa: E402
from src.editing import intake, pipeline, presets   # noqa: E402
from src.editing._util import probe                 # noqa: E402
from src.splitter import propose_candidates, split_video  # noqa: E402

TEST_VIDEO = Path.home() / "workspace/your_files/viral-clip-tool/test/source-test.mp4"
WORK = config.BASE_DIR / ".tmp" / "editing-test"
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    ok = bool(ok)  # coerce numpy bools etc. so the summary JSON dump works
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")


def loudness_i(path: Path) -> float:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path),
                        "-af", "loudnorm=print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=600)
    m = re.search(r'"input_i"\s*:\s*"(-?[\d.]+)"', r.stderr)
    return float(m.group(1)) if m else float("nan")


def rms_scan(path: Path) -> list[float]:
    wav = WORK / "scan.wav"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-i", str(path), "-vn", "-ac", "1", "-ar", "16000",
                    str(wav)], capture_output=True, timeout=300, check=True)
    import wave
    with wave.open(str(wav)) as w:
        frames = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    per_sec = []
    for i in range(0, len(frames) - 15999, 16000):
        seg = frames[i:i + 16000].astype(np.float64)
        rms = np.sqrt(np.mean(seg ** 2)) + 1e-9
        per_sec.append(20 * np.log10(rms / 32768.0))
    return per_sec


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    assert TEST_VIDEO.exists(), f"test video missing: {TEST_VIDEO}"

    # ---- 1. Intake / library -------------------------------------------
    entry = intake.add_to_library(str(TEST_VIDEO), "own",
                                  "Self-made test recording", name="e2e-test")
    check("intake add_to_library", Path(entry["path"]).exists(),
          f"id={entry['id']} dur={entry['duration']}")
    items = intake.list_library()
    check("intake list_library", any(i["id"] == entry["id"] for i in items))
    got = intake.get_library_item(entry["id"])
    check("intake get_library_item", got["rights"] == "own")
    for bad, why in [("https://www.youtube.com/watch?v=x", "watch URL"),
                     ("https://example.com/page.html", "non-media URL")]:
        try:
            intake.validate_media_url(bad)
            check(f"intake refuses {why}", False)
        except ValueError:
            check(f"intake refuses {why}", True)
    try:
        intake.add_to_library(str(TEST_VIDEO), "stolen", "x")
        check("intake rights gate", False)
    except ValueError:
        check("intake rights gate", True)

    # ---- 2. Transcript + candidates ------------------------------------
    tr = tools.get_transcript(entry["path"])
    check("transcript produced", bool(tr and tr.get("segments")),
          f"method={tr['method'] if tr else None} "
          f"segs={len(tr['segments']) if tr else 0}")
    cands = propose_candidates(tr["segments"], 30, 3) if tr else []
    check("candidates proposed", len(cands) >= 1, f"n={len(cands)}")
    if cands:
        start = cands[0].start_sec
        hook = cands[0].hook
    else:
        start, hook = 5.0, "Test hook line"
    end = start + 10.0

    # ---- 3. Full render: 9:16 + grade + hook + captions + clarity ------
    cfg = presets.build_config("Professional")
    out1 = WORK / "clip-pro.mp4"
    res = pipeline.render_segment(entry["path"], start, end, cfg, out1,
                                  WORK / "w1", extras={"hook_text": hook})
    info = probe(out1)
    check("render 9:16 dims", (info["width"], info["height"]) == (1080, 1920),
          f"{info['width']}x{info['height']}")
    check("render duration ~10s", abs(info["duration"] - 10.0) < 1.5,
          f"{info['duration']:.2f}s")
    check("captions applied", "captions" in res["applied"],
          f"applied={res['applied']} warnings={res['warnings']}")

    # ---- 4. Ratios 1:1 and 16:9 ----------------------------------------
    for ratio, dims in [("1:1", (1080, 1080)), ("16:9", (1920, 1080))]:
        c = presets.build_config("Minimal")
        c["reframe"]["params"]["ratio"] = ratio
        o = WORK / f"clip-{ratio.replace(':', 'x')}.mp4"
        pipeline.render_segment(entry["path"], start, start + 6, c, o,
                                WORK / f"w-{ratio}")
        i2 = probe(o)
        check(f"render {ratio} dims", (i2["width"], i2["height"]) == dims,
              f"{i2['width']}x{i2['height']}")

    # ---- 5. BGM ducking + loudness + RMS scan ---------------------------
    bgm = WORK / "bgm-test.wav"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "sine=frequency=330:duration=15",
                    "-af", "volume=0.6", str(bgm)],
                   capture_output=True, timeout=120, check=True)
    cfg2 = presets.build_config("Minimal")
    cfg2["bgm"] = {"enabled": True,
                   "params": {"music_level": 0.14, "bgm_path": str(bgm)}}
    out2 = WORK / "clip-bgm.mp4"
    res2 = pipeline.render_segment(entry["path"], start, end, cfg2, out2,
                                   WORK / "w2", extras={"hook_text": hook})
    check("bgm applied", "bgm" in res2["applied"],
          f"warnings={res2['warnings']}")
    li = loudness_i(out2)
    check("loudness ~-14 LUFS", abs(li - (-14.0)) <= 1.0, f"input_i={li}")
    scan = rms_scan(out2)
    if len(scan) >= 4:
        body = scan[1:-1] if len(scan) > 4 else scan
        mean = float(np.mean(body))
        worst = min(body)
        check("RMS scan no collapse", worst > mean - 25.0,
              f"mean={mean:.1f} dB worst={worst:.1f} dB secs={len(scan)}")
    else:
        check("RMS scan no collapse", False, f"only {len(scan)} seconds")

    # ---- 6. Op smoke: silence trim + zoom + transitions + PiP + logo ---
    logo = WORK / "logo.png"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=red:s=200x100",
                    "-frames:v", "1", str(logo)],
                   capture_output=True, timeout=60, check=True)
    cfg3 = presets.build_config("Custom")
    for op_id in ("silence_trim", "transitions", "zoom", "text_overlay",
                  "pip", "logo_overlay", "loudnorm"):
        cfg3[op_id]["enabled"] = True
    cfg3["text_overlay"]["params"]["text"] = "Smoke test"
    cfg3["reframe"] = {"enabled": True,
                       "params": {"ratio": "9:16", "mode": "blur"}}
    out3 = WORK / "clip-smoke.mp4"
    res3 = pipeline.render_segment(
        entry["path"], start, start + 12, cfg3, out3, WORK / "w3",
        extras={"pip_path": str(TEST_VIDEO), "logo_path": str(logo)})
    info3 = probe(out3)
    check("smoke render exists", out3.exists() and info3["duration"] > 3,
          f"applied={res3['applied']} warnings={res3['warnings']}")

    # ---- 7. Splitter regression (public signature unchanged) ------------
    results = split_video(entry["path"], "own", "Self-made test recording",
                          clip_len=10, max_clips=1)
    f0 = config.SHORTS_DIR / results[0]["file"]
    info4 = probe(f0)
    check("split_video regression",
          (info4["width"], info4["height"]) == (1080, 1920),
          f"{results[0]['file']} {info4['width']}x{info4['height']}")

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    print(json.dumps([{"check": n, "pass": ok, "detail": d}
                      for n, ok, d in RESULTS], indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
