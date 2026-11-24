"""intake.py — video input system + media library.

Accepts ONLY content the user has declared rights to:
- direct uploads (validated, size-capped),
- DIRECT media-file URLs (the URL must point at a media file —
  watch-page URLs such as youtube.com/watch are refused by this
  route; see the dedicated own-video route below),
- the user's OWN videos on watch pages (YouTube & similar) via
  add_watch_url_to_library() — same mandatory rights declaration,
  fetched with yt-dlp at <=720p, stored marked origin_kind=
  "watch-url" so the UI can auto-delete the (often large) source
  after rendering to save the user's disk space,
- items already in the media library.

Every accepted input is validated with ffprobe and stored under
data/library/ with a JSON index recording its rights declaration —
the same safety record the splitter has always kept.
"""
from __future__ import annotations

import json
import re
import shutil
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .. import config
from ..splitter import ALLOWED_RIGHTS
from ._util import probe

LIBRARY_DIR = config.DATA_DIR / "library"
INDEX_PATH = LIBRARY_DIR / "index.json"
ALLOWED_EXTS = {".mp4", ".mov", ".mkv", ".webm"}
MAX_BYTES = config.MAX_UPLOAD_MB * 1024 * 1024

_WATCH_HOSTS = ("youtube.com", "youtu.be", "vimeo.com", "tiktok.com",
                "instagram.com", "facebook.com", "fb.watch", "dailymotion.com",
                "twitch.tv", "x.com", "twitter.com")


def _load_index() -> list[dict]:
    if INDEX_PATH.exists():
        try:
            return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save_index(items: list[dict]) -> None:
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(items, indent=2), encoding="utf-8")


def validate_media_file(path: str | Path) -> dict:
    """Validate a local media file. Returns probe info.
    Raises ValueError with a clear, user-facing message."""
    p = Path(path)
    if not p.exists():
        raise ValueError(f"File not found: {p.name}")
    if p.suffix.lower() not in ALLOWED_EXTS:
        raise ValueError(
            f"Unsupported format '{p.suffix}'. Please use one of: "
            "MP4, MOV, MKV or WebM.")
    if p.stat().st_size > MAX_BYTES:
        raise ValueError(
            f"File too large — the limit is {config.MAX_UPLOAD_MB} MB.")
    info = probe(p)                       # raises ValueError if unreadable
    if info["duration"] <= 0:
        raise ValueError("Could not read the video's duration — "
                         "the file may be corrupt.")
    return info


def validate_media_url(url: str) -> str:
    """Validate an import URL. Only DIRECT media-file URLs are accepted;
    watch-page URLs are refused (use a file you own instead)."""
    u = (url or "").strip()
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("That doesn't look like a valid http(s) URL.")
    host = parsed.netloc.lower().split(":")[0]
    if any(host == h or host.endswith("." + h) for h in _WATCH_HOSTS):
        raise ValueError(
            "Watch-page URLs are not accepted. Please use a direct link "
            "to a media file you own or are licensed to use.")
    ext = Path(parsed.path).suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise ValueError(
            "The URL must point directly at a media file "
            "(.mp4, .mov, .mkv or .webm).")
    return u


def _download_direct(url: str, dest: Path) -> Path:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    written = 0
    with urllib.request.urlopen(req, timeout=120) as resp, \
            open(dest, "wb") as f:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > MAX_BYTES:
                f.close()
                dest.unlink(missing_ok=True)
                raise ValueError(
                    f"Download too large — the limit is "
                    f"{config.MAX_UPLOAD_MB} MB.")
            f.write(chunk)
    return dest


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:40] or "video"


def _check_rights(rights: str, source_note: str) -> None:
    """The rights gate shared by every intake route."""
    if rights not in ALLOWED_RIGHTS:
        raise ValueError(
            f"Rights declaration required — one of {sorted(ALLOWED_RIGHTS)}. "
            "The library only stores content you have the rights to use.")
    if len((source_note or "").strip()) < 3:
        raise ValueError("A source note is required (your safety record).")


def _store_local_file(local_src: Path, rights: str, source_note: str,
                      origin: str, name: str | None = None,
                      extra: dict | None = None) -> dict:
    """Validate a local media file and store it in the library,
    recording the rights declaration. Temp download files (names
    starting with '_') are removed after the copy."""
    info = validate_media_file(local_src)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    display = name or local_src.stem
    item_id = f"{stamp}-{_slug(display)}"
    dest = LIBRARY_DIR / f"{item_id}{local_src.suffix.lower()}"
    if local_src.resolve() != dest.resolve():
        shutil.copyfile(local_src, dest)
    if local_src.name.startswith("_"):
        local_src.unlink(missing_ok=True)

    entry = {
        "id": item_id,
        "name": display,
        "path": str(dest),
        "source": origin,
        "rights": rights,
        "source_note": source_note,
        "duration": round(info["duration"], 2),
        "size_mb": round(info["size"] / (1024 * 1024), 2),
        "width": info["width"],
        "height": info["height"],
        "format": info["format"],
        "added_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if extra:
        entry.update(extra)
    items = _load_index()
    items.append(entry)
    _save_index(items)
    return entry


def add_to_library(source: str, rights: str, source_note: str,
                   name: str | None = None) -> dict:
    """Validate + store an upload path or direct-media URL in the
    library, recording the rights declaration. Returns the index entry
    (which includes the local 'path' and library 'id')."""
    _check_rights(rights, source_note)
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)

    if source.startswith("http"):
        url = validate_media_url(source)
        ext = Path(urlparse(url).path).suffix.lower()
        tmp = LIBRARY_DIR / f"_download{ext}"
        _download_direct(url, tmp)
        local_src = tmp
        origin = url
    else:
        local_src = Path(source)
        origin = str(local_src)

    return _store_local_file(local_src, rights, source_note, origin, name)


def validate_watch_url(url: str) -> str:
    """Validate a watch-page URL for the own-video route. Only known
    watch hosts are accepted here; direct media-file URLs belong to
    validate_media_url instead."""
    u = (url or "").strip()
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("That doesn't look like a valid http(s) URL.")
    if Path(parsed.path).suffix.lower() in ALLOWED_EXTS:
        raise ValueError(
            "That URL points directly at a media file — please use "
            "the 'Direct media URL' source option for it instead.")
    host = parsed.netloc.lower().split(":")[0]
    if not any(host == h or host.endswith("." + h) for h in _WATCH_HOSTS):
        raise ValueError(
            "This source option supports YouTube and similar watch "
            "pages, for your own videos. For other sites, please use "
            "a direct media-file URL or upload the file.")
    return u


def _download_watch(url: str, dest_dir: Path) -> tuple[Path, str | None]:
    """Fetch a watch-page video with yt-dlp at <=720p (keeps files
    small on the user's disk). Returns (file path, page title).
    Raises ValueError with an honest, user-facing message."""
    import yt_dlp
    dest_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "format": ("bestvideo[height<=720]+bestaudio/"
                   "best[height<=720]/best"),
        "merge_output_format": "mp4",
        "outtmpl": str(dest_dir / "_watch.%(ext)s"),
        "max_filesize": MAX_BYTES,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as e:
        for f in dest_dir.glob("_watch.*"):
            f.unlink(missing_ok=True)
        raise ValueError(
            "Could not fetch this video from its URL. The site may "
            "have blocked the request — video sites often block "
            "server IPs, so this works most reliably in the app "
            "running on your own computer. "
            f"(Details: {type(e).__name__})") from e
    cands = [f for f in dest_dir.glob("_watch.*")
             if f.suffix.lower() in ALLOWED_EXTS]
    if not cands:
        raise ValueError(
            "The download finished but no usable video file was "
            "produced. Please try the file-upload option instead.")
    title = (info or {}).get("title") if isinstance(info, dict) else None
    return max(cands, key=lambda f: f.stat().st_size), title


def add_watch_url_to_library(url: str, rights: str,
                             source_note: str) -> dict:
    """Fetch the user's OWN watch-page video (e.g. their YouTube
    upload) into the library under the same mandatory rights
    declaration as every other route. The entry is marked
    origin_kind='watch-url' so the UI can delete the downloaded
    source after rendering (disk-space saving)."""
    _check_rights(rights, source_note)
    u = validate_watch_url(url)
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    local, title = _download_watch(u, LIBRARY_DIR)
    return _store_local_file(local, rights, source_note, origin=u,
                             name=title,
                             extra={"origin_kind": "watch-url"})


def remove_from_library(item_id: str) -> bool:
    """Delete a library item's file and index entry (used by the
    save-space auto-delete for URL-fetched sources). Returns True
    if an entry was removed."""
    items = _load_index()
    kept = []
    removed = False
    for it in items:
        if it["id"] == item_id:
            Path(it["path"]).unlink(missing_ok=True)
            removed = True
        else:
            kept.append(it)
    if removed:
        _save_index(kept)
    return removed


def list_library() -> list[dict]:
    """All library entries, newest first. Entries whose file has been
    deleted from disk are dropped from the result."""
    items = [it for it in _load_index() if Path(it["path"]).exists()]
    return list(reversed(items))


def get_library_item(item_id: str) -> dict:
    for it in _load_index():
        if it["id"] == item_id:
            if not Path(it["path"]).exists():
                raise ValueError("That library file is missing from disk.")
            return it
    raise ValueError("Library item not found.")
