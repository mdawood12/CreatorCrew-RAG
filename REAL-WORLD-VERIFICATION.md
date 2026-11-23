# Real-World Verification Runbook — CreatorCrew RAG

**Status of this document: NOT RUN — awaiting a real authorized sample.**

Every checklist item below is deliberately left unfilled. Nothing in
this runbook may be marked passed on the basis of the synthetic test
video, the sliding-photo face fixture, monkeypatched models, or any
other stand-in. Verification counts only when it is performed on a
**real video that the operator owns or is licensed to use**, with the
rights declaration recorded, and the generated outputs inspected.

When a run happens: fill in the Sample Log first, then work through
the sections in order, record actual results (including failures),
and update the status line of each section. Do not delete failing
results — record them and re-run after fixes.

Related: `VERIFICATION-ANALYSIS-2026-11-23.md` (what the existing
synthetic tests do and do not prove), `AUDIT-REPORT-2026-11-23.md`.

---

## Sample Log

| # | File | Source / rights basis | Duration | Resolution | Language(s) | Face(s)? | Date run | Run by |
|---|------|----------------------|----------|------------|-------------|----------|----------|--------|
| 1 | _NOT RUN_ | | | | | | | |
| 2 | _NOT RUN_ | | | | | | | |
| 3 | _NOT RUN_ | | | | | | | |
| 4 | _NOT RUN_ | | | | | | | |
| 5 | _NOT RUN_ | | | | | | | |

Target sample set (per the quality-gate standard): at least one
podcast/interview, one educational/explanatory, one discussion, one
motivational speech, one storytelling video — all authorized.

---

## 1. Ingestion cases

Run each case through the app's input system (file upload and, where
relevant, library import). Expected: no crash, clear error messages,
safe on-disk filenames, correct ffprobe metadata shown.

| # | Case | Expected behaviour | Result |
|---|------|--------------------|--------|
| 1.1 | Valid MP4 | Accepted; correct duration/resolution/codecs shown | NOT RUN |
| 1.2 | Valid MOV | Accepted; correct metadata shown | NOT RUN |
| 1.3 | Valid MKV | Accepted; correct metadata shown | NOT RUN |
| 1.4 | Valid WEBM | Accepted; correct metadata shown | NOT RUN |
| 1.5 | Unicode filename (e.g. اردو عنوان.mp4) | Accepted; stored under a safe filename; original title preserved in metadata | NOT RUN |
| 1.6 | Very long filename (>200 chars) | Accepted or cleanly rejected; no path errors | NOT RUN |
| 1.7 | Unsupported format (e.g. .avi/.flv renamed to .mp4) | Rejected with a clear message; no partial file left behind | NOT RUN |
| 1.8 | Corrupted video (truncated/bit-flipped) | Controlled error; app stays alive; no job marked complete | NOT RUN |
| 1.9 | Empty file (0 bytes) | Controlled error; clear message | NOT RUN |
| 1.10 | Video with no audio stream | Accepted for editing; transcription stage reports "no audio" cleanly, not a crash | NOT RUN |
| 1.11 | File over the 500 MB cap | Rejected with the size limit stated | NOT RUN |
| 1.12 | Duplicate upload of the same file | Handled without corrupting the library index | NOT RUN |

## 2. Transcription cases

For each case record: method used (transcript-api / yt-dlp-subs /
whisper), detected language, segment count, the sidecar
`word_timings` value, and a human spot-check of 3 segments against
the audio. **Interpolated timings must be labelled
"approximate (interpolated)" — never report them as word-accurate.**

| # | Case | What to verify | Result |
|---|------|----------------|--------|
| 2.1 | Clear English speech | Transcript matches audio; word timings word-level | NOT RUN |
| 2.2 | Noisy English (street/fan noise) | Transcript usable; if DTW fails, fallback engages and sidecar says "approximate (interpolated)" | NOT RUN |
| 2.3 | Urdu speech | Language detected as Urdu; transcript readable; caption rendering checked in §5 | NOT RUN |
| 2.4 | Hindi speech | Language detected; transcript readable | NOT RUN |
| 2.5 | Mixed-language (e.g. Urdu + English code-switching) | Transcript follows the switching without garbage segments | NOT RUN |
| 2.6 | Silence-only audio | No crash; empty/near-empty transcript handled gracefully downstream | NOT RUN |
| 2.7 | Speech over a music bed | Speech transcribed; music not transcribed as words | NOT RUN |
| 2.8 | Long pauses (≥5 s gaps) | No fabricated words inside pauses; segment boundaries sane | NOT RUN |
| 2.9 | Very short clip (<5 s) | Transcribes or fails cleanly; no exception | NOT RUN |
| 2.10 | Corrupted audio | Controlled error; no silent empty transcript presented as success | NOT RUN |
| 2.11 | Tiny vs Base selector | Re-run 2.1 with each model; confirm the selected model is the one actually used (log/config) and note quality difference | NOT RUN |

Timestamp sanity (apply to every case above): every word/segment has
start ≥ 0, end > start, end ≤ source duration, and words are in
order. Record any violation: NOT RUN.

## 3. Scoring review sheet

Complete one block **per sample**. The score is a heuristic
("Virality potential (heuristic)") — this sheet checks whether the
ranking and boundaries are sensible to a human, not whether the clip
will actually go viral.

### Sample #_ (file: ____________)

| Candidate | Start (s) | End (s) | Transcript excerpt | Score /100 | Top breakdown dimensions | Context complete? (Y/N) | Boundary clean? (starts/ends mid-sentence?) | Reviewer note |
|-----------|-----------|---------|--------------------|-----------|--------------------------|--------------------------|----------------------------------------------|---------------|
| 1 | | | | | | | | |
| 2 | | | | | | | | |
| 3 | | | | | | | | |

Checks for every sample (all NOT RUN until filled):
- [ ] Duplicate/near-duplicate candidates (>35% overlap) were removed.
- [ ] Selected duration (~10/15/20/30 s setting) was respected.
- [ ] Highest-scored candidate is plausibly the strongest moment (human judgement).
- [ ] Low-scoring content still returns useful alternatives, not an empty list.
- [ ] No candidate begins or ends mid-word.

## 4. Computer-vision scenarios (smart reframe)

Use real footage. For each scenario render a 9:16 clip with the
"smart" reframe mode and **watch the rendered video** — a detection
count alone is not verification.

| # | Scenario | What to verify in the rendered clip | Result |
|---|----------|--------------------------------------|--------|
| 4.1 | One person, fairly still | Face stays in frame; crop steady, no jitter | NOT RUN |
| 4.2 | Person moving left → right | Crop follows smoothly (EMA/deadband); no sudden jumps; face not cut off | NOT RUN |
| 4.3 | Person moving right → left | Same as 4.2 in the other direction | NOT RUN |
| 4.4 | Two people in frame | Behaviour is sane (one tracked / centred between them); nobody is cropped out mid-sentence without reason | NOT RUN |
| 4.5 | Person leaves frame and returns | No wild crop swings while absent; fallback engages; crop recovers on return | NOT RUN |
| 4.6 | No face in frame at all | Falls back cleanly (blur-pad/centre); output still valid 1080×1920 | NOT RUN |
| 4.7 | Low-light footage | Detection behaviour recorded honestly (works / degraded / fallback) | NOT RUN |
| 4.8 | Portrait (9:16) source video | Reframe does not crop destructively; output correct | NOT RUN |

For every scenario: no black borders, no cropped-off heads where a
face was reliably detectable, output dimensions exactly 1080×1920.
Record the detector that actually ran (YuNet / Haar / fallback):
NOT RUN.

## 5. Render checks

Apply to **every** rendered clip from §§3–4 (and at least three
clips from real samples end-to-end).

| # | Check | How | Result |
|---|-------|-----|--------|
| 5.1 | File exists and size is plausible (>0, sane for duration) | `ls -l` / file manager | NOT RUN |
| 5.2 | ffprobe: dimensions match the requested ratio (1080×1920 / 1080×1080 / 1920×1080) | `ffprobe -v error -show_streams -show_format <file>` | NOT RUN |
| 5.3 | ffprobe: duration within ~0.5 s of the requested window | Same as above | NOT RUN |
| 5.4 | ffprobe: one H.264 video stream + one AAC audio stream present (unless source had no audio) | Same as above | NOT RUN |
| 5.5 | Loudness ≈ −14 LUFS ±1, true peak ≤ −1 dB | `ffmpeg -i <file> -af loudnorm=print_format=json -f null -` | NOT RUN |
| 5.6 | Caption sync spot-check: pause at 3 spoken moments; the on-screen caption matches the word being spoken at that instant | Play the MP4 | NOT RUN |
| 5.7 | Karaoke style: active word highlights in time with speech | Play the MP4 | NOT RUN |
| 5.8 | Urdu captions (if an Urdu sample was used): RTL order, character shaping, no tofu boxes, readable font | Play the MP4 | NOT RUN |
| 5.9 | No audio collapse: per-second RMS has no unexplained dropouts | RMS scan (see editing e2e method) | NOT RUN |
| 5.10 | Clip plays end-to-end in a normal player without errors | VLC / browser player | NOT RUN |

## 6. Benchmark table (template — no numbers pre-filled)

Run with: `.venv/bin/python scripts/benchmark.py <video>` on the
machine whose performance is being claimed. One row per run; never
copy numbers between machines or between videos.

| Date | Machine (CPU / RAM / OS) | Video (duration, resolution) | Model | Transcribe (s) | Analysis/scoring (s) | Render (s, which preset & length) | Total (s) | Peak memory note | Notes |
|------|--------------------------|------------------------------|-------|----------------|----------------------|-----------------------------------|-----------|------------------|-------|
| | | | tiny | | | | | | |
| | | | base | | | | | | |

Required comparisons (all NOT RUN):
- [ ] Tiny vs Base on the **same** video and machine (speed and transcript quality).
- [ ] One long video (≥10 min) end-to-end, total wall-clock recorded.
- [ ] Low-memory behaviour: note any swapping/failure honestly.

---

## Sign-off

| Item | Status |
|------|--------|
| Samples collected (authorized, rights recorded) | NOT RUN |
| §1 Ingestion | NOT RUN |
| §2 Transcription | NOT RUN |
| §3 Scoring review | NOT RUN |
| §4 Vision scenarios | NOT RUN |
| §5 Render checks | NOT RUN |
| §6 Benchmarks | NOT RUN |
| Upgraded app run once on the owner's Windows PC | NOT RUN |
