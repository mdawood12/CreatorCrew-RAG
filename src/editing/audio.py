"""audio.py — voice clarity, background music with ducking, loudnorm.

BGM method (learned the hard way — see AGENTS.md): stems are rendered
SEPARATELY, mixed with sidechaincompress, and loudness is normalised by
the separate loudnorm stage afterwards. A single filter graph that
combines beds + ducking + voice + loudnorm collapses the mix, so it is
never used here.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from . import registry
from ._util import probe, run_ffmpeg


def voice_clarity(in_path: Path, params: dict, ctx: dict) -> Path:
    if not probe(in_path)["has_audio"]:
        return in_path
    af = (f"highpass=f={int(params['highpass_hz'])}"
          f",afftdn=nf={params['noise_floor']:.0f}"
          f",equalizer=f=3000:width_type=o:width=2:g={params['presence_db']:.1f}")
    out = ctx["workdir"] / f"{in_path.stem}_clarity.mp4"
    run_ffmpeg(["-i", str(in_path), "-c:v", "copy", "-af", af,
                "-c:a", "aac", "-b:a", "160k", str(out)])
    return out


def bgm_mix(in_path: Path, params: dict, ctx: dict) -> Path:
    bgm = ctx.get("extras", {}).get("bgm_path") or params.get("bgm_path")
    if not bgm or not Path(bgm).exists():
        raise ValueError("Background music needs a music file — "
                         "add one in the editing panel.")
    info = probe(in_path)
    if not info["has_audio"]:
        raise ValueError("This clip has no audio to duck the music under.")
    dur = info["duration"]
    workdir = ctx["workdir"]
    level = float(params["music_level"])       # 0..1 linear bed level

    # Stem 1 — the clip's own audio (the voice).
    voice_wav = workdir / f"{in_path.stem}_voice.wav"
    run_ffmpeg(["-i", str(in_path), "-vn", "-ac", "2", "-ar", "48000",
                str(voice_wav)])
    # Stem 2 — music bed: looped/trimmed to length, faded, set to level.
    bed_wav = workdir / f"{in_path.stem}_bed.wav"
    run_ffmpeg(["-stream_loop", "-1", "-i", str(bgm),
                "-t", f"{dur:.3f}", "-vn", "-ac", "2", "-ar", "48000",
                "-af", f"volume={level:.3f},afade=t=in:st=0:d=0.4,"
                       f"afade=t=out:st={max(dur - 0.6, 0):.3f}:d=0.6",
                str(bed_wav)])
    # Mix — sidechain-duck the bed under the voice, then add them.
    # Input 0 is the BED (the stream being ducked); input 1 is the VOICE
    # (split into the sidechain key + the audible voice) — order matters.
    # Compressor settings are the proven production values.
    mix_wav = workdir / f"{in_path.stem}_mix.wav"
    graph = ("[1:a]asplit[key][voice];"
             "[0:a][key]sidechaincompress=threshold=0.03:ratio=8:"
             "attack=20:release=450[ducked];"
             "[voice][ducked]amix=inputs=2:duration=first:"
             "dropout_transition=0:normalize=0[out]")
    r = subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-i", str(bed_wav), "-i", str(voice_wav),
         "-filter_complex", graph, "-map", "[out]",
         "-ac", "2", "-ar", "48000", str(mix_wav)],
        capture_output=True, text=True, timeout=1200)
    if r.returncode != 0:
        raise RuntimeError("BGM mix failed: " + (r.stderr or "")[-500:])
    # Mux — video stream copied untouched, mixed audio encoded.
    out = workdir / f"{in_path.stem}_bgm.mp4"
    run_ffmpeg(["-i", str(in_path), "-i", str(mix_wav),
                "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                "-c:a", "aac", "-b:a", "160k", "-shortest", str(out)])
    return out


def loudnorm(in_path: Path, params: dict, ctx: dict) -> Path:
    if not probe(in_path)["has_audio"]:
        return in_path
    out = ctx["workdir"] / f"{in_path.stem}_loud.mp4"
    run_ffmpeg(["-i", str(in_path), "-c:v", "copy",
                "-af", f"loudnorm=I={params['target_lufs']:.1f}"
                       f":TP={params['true_peak']:.1f}:LRA=11",
                "-c:a", "aac", "-b:a", "192k", str(out)])
    return out


registry.register(registry.Operation(
    id="voice_clarity", stage="audio", phase="A", label="Voice clarity",
    help="Cleans the voice: removes rumble and noise, adds presence.",
    func=voice_clarity,
    params=[
        {"key": "highpass_hz", "type": "int", "default": 80, "min": 40,
         "max": 200, "step": 10, "label": "Rumble cut-off (Hz)",
         "help": "Removes low rumble below this frequency."},
        {"key": "noise_floor", "type": "float", "default": -25.0, "min": -50.0,
         "max": -10.0, "step": 1.0, "label": "Noise floor (dB)",
         "help": "How aggressive the noise reduction is."},
        {"key": "presence_db", "type": "float", "default": 3.0, "min": 0.0,
         "max": 8.0, "step": 0.5, "label": "Presence boost (dB)",
         "help": "Lifts the voice frequencies so words cut through."},
    ]))
registry.register(registry.Operation(
    id="bgm", stage="audio", phase="B", label="Background music + ducking",
    help="Adds a music bed that automatically dips under the voice.",
    func=bgm_mix,
    params=[
        {"key": "music_level", "type": "float", "default": 0.14, "min": 0.02,
         "max": 0.5, "step": 0.01, "label": "Music level",
         "help": "Bed volume before ducking (0.10–0.15 is subtle)."},
        {"key": "bgm_path", "type": "text", "default": "", "label": "Music file path",
         "help": "Filled automatically when you add music in the panel."},
    ]))
registry.register(registry.Operation(
    id="loudnorm", stage="loudnorm", phase="A", label="Loudness mastering",
    help="Normalises loudness to the platform standard (-14 LUFS).",
    func=loudnorm,
    params=[
        {"key": "target_lufs", "type": "float", "default": -14.0, "min": -20.0,
         "max": -10.0, "step": 0.5, "label": "Target loudness (LUFS)",
         "help": "-14 LUFS is the YouTube/Facebook standard."},
        {"key": "true_peak", "type": "float", "default": -1.0, "min": -3.0,
         "max": -0.5, "step": 0.5, "label": "True peak ceiling (dB)",
         "help": "Maximum peak level after mastering."},
    ]))
