"""editing — modular video editing engine (see MASTER-PROMPT-VIDEO-EDITING.md).

One module per operation, a single registry, a fixed pipeline order and
full isolation: a failing operation is skipped with a warning and never
kills a render or another module. Zero-cost components only (FFmpeg,
faster-whisper)."""
