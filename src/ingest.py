"""
ingest.py — Real-world dataset ingestion -> ChromaDB [Phase 2].

Pipeline: load -> clean -> metadata -> chunk -> embed (local) -> store.
- Sources [C6]: files dropped into data/raw/ (.txt .md .pdf .csv),
  official policy pages from config.POLICY_URLS, and viral-video
  transcripts from data/raw/viral_urls.txt via the fallback chain [C5].
  No Kaggle account or paid service anywhere.
- Idempotency: every chunk id is a content hash — re-running ingestion
  adds ZERO duplicate chunks.
Run:  python -m src.ingest
"""
from __future__ import annotations

import csv
import hashlib
import io
import urllib.request

from . import config
from .config import logger

TEXT_EXTS = (".txt", ".md")
SUPPORTED = TEXT_EXTS + (".pdf", ".csv")


def chunk_id(text: str, source: str) -> str:
    return hashlib.sha256((source + "::" + text).encode("utf-8")).hexdigest()[:24]


def _read_file(path) -> str:
    ext = path.suffix.lower()
    if ext in TEXT_EXTS:
        return path.read_text(encoding="utf-8", errors="ignore")
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    if ext == ".csv":
        rows = list(csv.reader(io.StringIO(
            path.read_text(encoding="utf-8", errors="ignore"))))
        return "\n".join(" | ".join(r) for r in rows)
    return ""


def _fetch_url(url: str) -> str:
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url)
        text = trafilatura.extract(downloaded) if downloaded else None
        if text:
            return text
    except Exception as e:
        logger.warning("trafilatura failed for %s: %s", url, e)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def collect_documents() -> list[dict]:
    """Return [{text, metadata}] from every configured real source."""
    docs: list[dict] = []
    # 1) Local real dataset files
    for path in sorted(config.RAW_DIR.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED:
            text = _read_file(path).strip()
            if not text:
                continue
            name = path.name.lower()
            doc_type = ("platform_policy" if "polic" in name
                        else "viral_transcript")
            docs.append({"text": text, "metadata": {
                "doc_type": doc_type, "platform": "mixed",
                "source": f"file:{path.name}"}})
            logger.info("Loaded file %s (%d chars)", path.name, len(text))
    # 2) Official policy pages
    for item in config.POLICY_URLS:
        try:
            text = _fetch_url(item["url"]).strip()
            if len(text) > 200:
                docs.append({"text": text, "metadata": {
                    "doc_type": item["doc_type"], "platform": item["platform"],
                    "source": item["source"]}})
                logger.info("Fetched policy %s (%d chars)",
                            item["source"], len(text))
        except Exception as e:
            logger.warning("Policy fetch failed (%s): %s", item["url"], e)
    # 3) Viral transcripts from URL list (fallback chain lives in tools.py)
    if config.VIRAL_URLS_FILE.exists():
        from .tools import get_transcript
        for line in config.VIRAL_URLS_FILE.read_text().splitlines():
            url = line.strip()
            if not url or url.startswith("#"):
                continue
            try:
                tr = get_transcript(url)
                if tr and tr["text"].strip():
                    docs.append({"text": tr["text"], "metadata": {
                        "doc_type": "viral_transcript", "platform": "youtube",
                        "source": url}})
                    logger.info("Transcript ingested: %s", url)
            except Exception as e:
                logger.warning("Transcript failed (%s): %s", url, e)
    return docs


def get_embeddings():
    from langchain_huggingface import HuggingFaceEmbeddings
    return HuggingFaceEmbeddings(model_name=config.EMBEDDING_MODEL)


def get_vectorstore():
    from langchain_chroma import Chroma
    return Chroma(persist_directory=str(config.CHROMA_DIR),
                  embedding_function=get_embeddings(),
                  collection_name="creatorcrew")


def build_index() -> dict:
    """Chunk + embed + store, idempotently. Returns a small report."""
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from langchain_core.documents import Document

    docs = collect_documents()
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE, chunk_overlap=config.CHUNK_OVERLAP)
    chunks: list[Document] = []
    seen: set[str] = set()
    for d in docs:
        for piece in splitter.split_text(d["text"]):
            piece = piece.strip()
            if not piece:
                continue
            cid = chunk_id(piece, d["metadata"]["source"])
            if cid in seen:
                continue
            seen.add(cid)
            chunks.append(Document(page_content=piece,
                                   metadata=d["metadata"], id=cid))
    store = get_vectorstore()
    added = 0
    if chunks:
        existing = set(store.get(include=[])["ids"])
        new = [c for c in chunks if c.id not in existing]
        if new:
            store.add_documents(new)
            added = len(new)
    total = len(store.get(include=[])["ids"])
    report = {"documents": len(docs), "chunks_considered": len(chunks),
              "chunks_added": added, "chunks_total": total}
    logger.info("Ingest report: %s", report)
    return report


if __name__ == "__main__":
    print(build_index())
