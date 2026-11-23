# CreatorCrew — Video Editing Upgrade Plan (SAVED 2026-11-23, build NOT started)

Source: user's "Advanced AI Video Editing & Automated Short-Form Production" master prompt (2026-11-22).
User decision: **plan only — build decision later.** Simplicity rule applies: one phase at a time.

## Audit — already in the app
- Intelligent scene cutting (splitter segment scoring + candidates)
- Smart vertical reframing (blur-pad / crop, 9:16)
- Color grading + brightness/contrast (in render_clip)
- Hook overlay (drawtext), progress bar
- Audio normalization (loudnorm I=-14)
- Whisper subtitle engine exists in tools.py (transcripts) — not yet burned onto clips
- Transformation Planner (7-stage editorial plan) in Splitter tab, Step 4

## Phase A — presets + control over what already renders (highest value, lowest complexity)
- 5 presets: Professional / Cinematic / Social Media / Minimal / Custom
- Per-clip toggles + intensity for existing renders: reframe mode, grade on/off, hook on/off, loudnorm on/off
- Aspect ratios: add 1:1 and 16:9 to the existing 9:16
- Batch ZIP download of clips

## Phase B — render additions
- Burn Whisper captions onto clips (word/phrase chunks, ASS)
- Royalty-free BGM mix + automatic ducking in the render (stems-separate method, per past audio lesson)
- Silence trimming option
- Dynamic transitions between segments (xfade)

## Parked — heavy / not viable on free Streamlit Cloud
- Real-time preview, original-vs-edited compare, timeline editor
- Background processing queue
- 4K / 60fps export
(PC/local version could host these later as a separate project — only on user's word.)

## Open loop before any build
- GitHub upload of README.md + app.py (root) and src/planner.py — one trip, three files.

## Combined options map (2026-11-23 — user's 20-option prompt + Ali Ai Studio analysis)
Ali Ai Studio (friend's tool) findings: Smart Import (YouTube/IG/TikTok/Douyin URLs), Groq Whisper transcription (free), Gemini multimodal video intelligence (scene understanding + retention-hook detection, ~5-min chunks, free tier), built-in voices = Microsoft Edge neural TTS (Christopher/Jenny/Guy/Sonia — free, no key), timeline editor + 1080p export. Paid add-ons (ElevenLabs etc.) excluded by zero-cost rule.
Borrowable at zero cost: Groq Whisper speed, Gemini video intelligence (user already has the key), Edge-TTS voices, translate+rewrite flow.
UI/UX direction: wizard cards (Import → Analyze → Edit → Export), stat cards, one accent color, theme config + light custom CSS, plain-language labels, progress + friendly errors. Honest limit: Ali-Studio-grade custom desktop UI is not possible in Streamlit; custom frontend stays parked.

## Ali Ai Studio — FULL analysis (verified from 8 screenshots, 2026-11-23)
Desktop app (friend's tool, ~84 MB installer). Purpose: repurpose foreign/social videos into English content.
- Flow: Smart Import (YouTube/TikTok/Instagram/Facebook/Douyin URLs via built-in downloader up to 4K, or local files) → Groq Whisper transcription (free, word-level) → Gemini multimodal analysis (scenes, retention hooks, rewrite, language detection; 300s/request, auto-partition) → natural English rewrite + translation → built-in Edge neural voices (Christopher/Jenny/Guy/Sonia) → synced captions → timeline editing + dynamic framing → 1080p MP4 export.
- Prompt Extractor: any video ≤120s → reconstructed cinematic prompt formula + master production blueprint (Gemini vision; a reconstruction/estimate, not the original prompt).
- Dashboard: project library (All/Ready/Drafts/Prompts), search, grid/list. Settings: providers Groq, Gemini Analysis, Gemini Voice (separate key), OpenAI (paid), ElevenLabs (paid), ai33.pro (paid aggregator). Keys in Windows Credential Manager.
- NOT visually verified: the in-editor timeline screen (needs keys + import). Claimed on welcome screen: visual timeline editing, dynamic framing, fast 1080p export — already covered in our plan (Phase B / parked).
- Borrowed into our plan: Groq fast transcription, Gemini video intelligence, Edge-TTS voices, Prompt-Extractor-style blueprint (Phase B analysis module), project-library dashboard structure. Skipped: platform downloader (rights/ToS), paid voice add-ons, desktop-app UI.
