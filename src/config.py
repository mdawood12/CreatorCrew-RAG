"""
config.py — Central configuration, environment validation & API Key Manager.

Design notes (from the FINAL master prompt v2):
- [C7]  Everything configurable lives here — never hard-code model names,
        chunk sizes or paths inside feature modules.
- [C15] KeyManager: a POOL of free Gemini keys. The app health-checks the
        active key and automatically fails over to the next key on quota
        (HTTP 429) or invalid/revoked (HTTP 403) errors, so work does not
        stop or slow down. An app CANNOT regenerate a Gemini key by itself
        (that needs the owner's Google sign-in at AI Studio) — if the whole
        pool is down, the UI shows the 1-minute manual steps instead.
- [C16] MODEL_CHAIN: the model-level twin of the key pool. A model error
        (404/not found, 503/overloaded) advances to the next model in the
        chain instead of stopping the app; key errors keep rotating keys
        on the same model. LLM_MODELS overrides the chain; LLM_MODEL
        remains the primary.
- [C4]  No key is NOT a crash: the app runs in demo mode (RAG, memory,
        splitter and UI all work; only LLM buttons ask for a key).
- [C3]  LangSmith tracing turns on only when LANGCHAIN_API_KEY is set.
This module uses only the Python standard library + python-dotenv (if
installed), so `config.validate()` works even before the full install.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import urllib.request
import urllib.error
from pathlib import Path

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
EVAL_DIR = DATA_DIR / "eval"
CHROMA_DIR = DATA_DIR / "chroma_db"
OUTPUTS_DIR = BASE_DIR / "outputs"
SHORTS_DIR = OUTPUTS_DIR / "shorts"
STORAGE_DIR = BASE_DIR / "storage"
DB_PATH = STORAGE_DIR / "creator_memory.db"
LOG_PATH = STORAGE_DIR / "app.log"

for _p in (RAW_DIR, EVAL_DIR, CHROMA_DIR, SHORTS_DIR, STORAGE_DIR):
    _p.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------------
# Environment (.env)
# --------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except Exception:  # python-dotenv not installed yet — parse .env manually
    _env_file = BASE_DIR / ".env"
    if _env_file.exists():
        for _line in _env_file.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

# --------------------------------------------------------------------------
# Model / RAG settings
# --------------------------------------------------------------------------
# Default model: gemini-3-flash-preview. NOTE (verified 2026-11-19 against a
# fresh free-tier key): gemini-2.5-flash now returns 404 "no longer available
# to new users", so new keys must use a Gemini 3 flash model. Override with
# the LLM_MODEL environment variable if Google rotates availability again.
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-3-flash-preview")


def _parse_model_chain() -> list[str]:
    """The ordered MODEL BACKUP CHAIN [C16] — the model-level twin of
    the key pool: if LLM_MODELS is set, it wins (comma-separated);
    otherwise the primary (LLM_MODEL) followed by the stable fallbacks.
    Deduped, order preserved, never empty."""
    raw = os.getenv("LLM_MODELS", "")
    names = ([m.strip() for m in raw.split(",")] if raw.strip()
             else [LLM_MODEL, "gemini-2.5-flash", "gemini-2.5-flash-lite"])
    chain: list[str] = []
    for name in names:
        if name and name not in chain:
            chain.append(name)
    return chain or [LLM_MODEL]


MODEL_CHAIN = _parse_model_chain()
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
TOP_K = 5
MAX_REVISIONS = 2                 # bounded critic loop — never infinite
TEMP_SCRIPT = 0.7                 # creative writing
TEMP_CRITIC = 0.2                 # strict auditing
MAX_UPLOAD_MB = 500

# Local Whisper model for transcription (splitter/captions path):
# "base" (High Accuracy) is the default — the 2026-11-23 real-world
# verification found tiny mis-hearing key vocabulary ("microplastics"
# -> "microblastics") while base cost only ~3.6 s more on a 6.5 min
# programme. "tiny" (Ultra-Fast) remains selectable. Override with
# the WHISPER_MODEL env var; the Splitter tab's selector sets this
# at runtime.
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")

# Official policy sources ingested by ingest.py (real documents, no Kaggle
# login needed — correction C6). Failure to fetch one is a warning, not fatal.
POLICY_URLS = [
    {"url": "https://support.google.com/youtube/answer/1311392",
     "doc_type": "platform_policy", "platform": "youtube",
     "source": "YouTube Help — Copyright"},
    {"url": "https://www.facebook.com/help/249141925204375",
     "doc_type": "platform_policy", "platform": "facebook",
     "source": "Meta Help — Intellectual Property"},
]
VIRAL_URLS_FILE = RAW_DIR / "viral_urls.txt"

# LangSmith tracing — opt-in only [C3]
if os.getenv("LANGCHAIN_API_KEY"):
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_PROJECT", "CreatorCrew-RAG")
else:
    os.environ["LANGCHAIN_TRACING_V2"] = "false"

# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"),
              logging.StreamHandler()],
)
logger = logging.getLogger("creatorcrew")


def mask(key: str) -> str:
    """Show only the last 4 characters of a key — full keys are never logged."""
    return ("..." + key[-4:]) if key and len(key) > 4 else "(empty)"


# --------------------------------------------------------------------------
# [C15] API Key Manager — pool, health check, automatic failover
# --------------------------------------------------------------------------
class KeyManager:
    """Manages the pool of free Gemini API keys from GOOGLE_API_KEYS.

    - health_check(): one tiny free call to the Gemini models endpoint.
    - report_failure(status): on 429 (quota) or 403 (invalid/revoked),
      switch to the next key and return it (or None if the pool is down).
    - The manager NEVER creates/regenerates keys — that requires the
      owner's Google sign-in. REGENERATION_STEPS is what the UI shows
      when every key is down; recovery takes about one minute.
    """

    REGENERATION_STEPS = (
        "All API keys are down. To recover in about 1 minute:\n"
        "1. Open https://aistudio.google.com/apikey (sign in with your Google account)\n"
        "2. Click 'Create API key' and copy the new key\n"
        "3. Paste it into the .env file as GOOGLE_API_KEYS=your-new-key\n"
        "4. Restart the app"
    )

    # Obvious placeholder values that must never be treated as real
    # keys (the Streamlit Secrets incident: the template text "apni-key"
    # was pasted verbatim and the app reported a healthy key for hours).
    # Real Gemini keys are opaque tokens — they never contain readable
    # placeholder words — so a general marker filter is safe.
    _PLACEHOLDER_MARKERS = (
        "your", "placeholder", "example", "change-me", "changeme",
        "insert", "replace", "todo", "xxxx", "apni", "dummy", "fake",
        "sample", "enter-key", "paste", "here", "api-key", "apikey",
    )

    @staticmethod
    def _is_placeholder(key: str) -> bool:
        k = key.strip().strip('"').strip("'").lower()
        if len(k) < 8:
            return True
        return any(m in k for m in KeyManager._PLACEHOLDER_MARKERS)

    def __init__(self, keys: list[str] | None = None):
        if keys is None:
            raw = os.getenv("GOOGLE_API_KEYS", "") or os.getenv("GOOGLE_API_KEY", "")
            keys = [k.strip() for k in raw.split(",")
                    if k.strip() and not self._is_placeholder(k)]
        self.keys = keys
        self.active = 0
        self.dead: set[int] = set()

    # -- basics ------------------------------------------------------------
    @property
    def has_keys(self) -> bool:
        return len(self.keys) > 0

    def current_key(self) -> str | None:
        if not self.has_keys or self.active >= len(self.keys):
            return None
        return self.keys[self.active]

    # -- health ------------------------------------------------------------
    def health_check(self, key: str | None = None, timeout: int = 10) -> bool:
        """True if the key is accepted by the Gemini API (free models call)."""
        key = key or self.current_key()
        if not key:
            return False
        url = ("https://generativelanguage.googleapis.com/v1beta/models"
               f"?key={key}")
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status == 200
        except urllib.error.HTTPError as e:
            logger.warning("Key %s health check failed: HTTP %s", mask(key), e.code)
            return False
        except Exception as e:  # network down etc.
            logger.warning("Key %s health check error: %s", mask(key), e)
            return False

    # -- failover ----------------------------------------------------------
    def report_failure(self, status_code: int | None = None) -> str | None:
        """Mark the active key as failed (quota/invalid) and switch.

        Returns the next usable key, or None when the pool is exhausted.
        """
        if not self.has_keys:
            return None
        logger.warning("Key %s failed (status=%s) — switching to next key",
                       mask(self.keys[self.active]), status_code)
        self.dead.add(self.active)
        for i, _k in enumerate(self.keys):
            if i not in self.dead:
                self.active = i
                logger.info("Active key is now %s", mask(self.keys[i]))
                return self.keys[i]
        logger.error("API key pool exhausted")
        return None

    def status(self) -> dict:
        """UI-friendly status (keys always masked)."""
        if not self.has_keys:
            return {"state": "no_key", "label": "No API key — Demo Mode",
                    "pool_size": 0, "active": None}
        down = len(self.dead) >= len(self.keys)
        return {
            "state": "down" if down else "active",
            "label": ("All keys down — see recovery steps" if down
                      else f"Key active {mask(self.keys[self.active])}"),
            "pool_size": len(self.keys),
            "active": None if down else mask(self.keys[self.active]),
            "dead": len(self.dead),
        }


KEY_MANAGER = KeyManager()


def get_llm(temperature: float = TEMP_SCRIPT, model: str | None = None):
    """LLM factory [C12/C15] — every agent gets its model through here,
    so the provider and the key pool can change without touching agents.
    `model` overrides the primary (used by the backup chain [C16]);
    the default is LLM_MODEL, exactly as before."""
    key = KEY_MANAGER.current_key()
    if not key:
        return None  # demo mode [C4]
    from langchain_google_genai import ChatGoogleGenerativeAI
    # transport="rest": the default gRPC transport hangs behind HTTP proxies
    # (verified in sandbox testing); REST works through proxies everywhere.
    return ChatGoogleGenerativeAI(
        model=model or LLM_MODEL, google_api_key=key,
        temperature=temperature, transport="rest")


def _key_error_status(msg: str) -> int | None:
    """Classify a failure message as a KEY problem [C15]: 429 (quota)
    or 403 (invalid/revoked key). Same substring rules as always."""
    if "429" in msg or "quota" in msg or "rate" in msg:
        return 429
    if "403" in msg or "api key" in msg or "permission" in msg:
        return 403
    return None


def _is_model_error(msg: str) -> bool:
    """True when the MODEL itself is the problem [C16]: it does not
    exist for this API version (404 / not found), or the service is
    down or overloaded (503 / unavailable). Rotating keys cannot fix
    these — the backup chain advances to the next model instead."""
    return any(s in msg for s in
               ("404", "not found", "not_found", "503",
                "unavailable", "overloaded"))


def call_llm_with_failover(make_call, attempts: int = 3):
    """Run make_call(llm) with two layers of failover, so one failure
    never stops the app:

    - KEY errors (429 quota / 403 invalid) rotate the key pool [C15]
      and retry the SAME model, up to `attempts` times per model.
    - MODEL errors (404 / not found / 503 / overloaded) advance to the
      next model in MODEL_CHAIN [C16] and retry with the same key.
    - Any other error raises immediately, as before.

    Total tries are bounded by len(MODEL_CHAIN) x attempts. If every
    model fails, raises a RuntimeError carrying the recovery steps.
    """
    import time
    last_err = None
    models = list(MODEL_CHAIN) or [LLM_MODEL]
    for model in models:
        for attempt in range(attempts):
            llm = get_llm(model=model)
            if llm is None:
                raise RuntimeError("No API key configured (demo mode).")
            try:
                return make_call(llm)
            except Exception as e:  # inspect for key / model problems
                last_err = e
                msg = str(e).lower()
                status = _key_error_status(msg)
                if status is not None:
                    logger.warning("LLM call failed (%s) on %s, attempt %s",
                                   status, model, attempt + 1)
                    if KEY_MANAGER.report_failure(status) is None:
                        raise RuntimeError(
                            "All API keys failed. "
                            + KeyManager.REGENERATION_STEPS) from last_err
                    time.sleep(2 * (attempt + 1))  # backoff before retry
                    continue
                if _is_model_error(msg):
                    logger.warning("Model %s unavailable (%s) — "
                                   "switching to the next model in the "
                                   "chain", model, str(e)[:120])
                    break  # next model, same key
                raise
    raise RuntimeError(
        "All API keys failed (every model in the backup chain was "
        f"tried: {', '.join(models)}). "
        + KeyManager.REGENERATION_STEPS) from last_err


# --------------------------------------------------------------------------
# Validation (Phase 1 gate)
# --------------------------------------------------------------------------
def validate() -> dict:
    """Check paths, FFmpeg and key status. Returns a report dict."""
    report = {
        "base_dir": str(BASE_DIR),
        "ffmpeg": shutil.which("ffmpeg") or "NOT FOUND",
        "ffprobe": shutil.which("ffprobe") or "NOT FOUND",
        "key_status": KEY_MANAGER.status(),
        "langsmith": os.environ.get("LANGCHAIN_TRACING_V2") == "true",
        "model": LLM_MODEL,
        "embedding_model": EMBEDDING_MODEL,
    }
    for d in (RAW_DIR, CHROMA_DIR, SHORTS_DIR, STORAGE_DIR):
        d.mkdir(parents=True, exist_ok=True)
    if report["ffmpeg"] == "NOT FOUND":
        logger.warning("FFmpeg not found on PATH. On Windows install it with: "
                       "winget install Gyan.FFmpeg — then reopen the terminal.")
    logger.info("Config validation: %s", json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    print(json.dumps(validate(), indent=2))
