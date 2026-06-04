"""Phase 3 — Storage (zero-config, local files).

SQLite holds structured metadata (one row per judgement, from data/manifest.json
plus extracted fields) for fast filtering by judge / date / case_no. ChromaDB
holds the embeddings for semantic search. Both are plain local files under data/
— no server.

Embeddings: uses `BAAI/bge-m3` (multilingual) when sentence-transformers is
installed; otherwise falls back to Chroma's built-in default embedder (English,
light) so the pipeline runs out-of-the-box. The collection name encodes which,
so the two never collide. After `pip install -r requirements.txt`, re-run the
index to switch to bge-m3.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

import chromadb

from .config import settings
from .ingest import Chunk


def _embedding_function():
    # ROSCRIBE_EMBEDDER=default forces the light MiniLM embedder / collection,
    # even when sentence-transformers is installed (used while the bge-m3
    # re-index is incomplete).
    if os.getenv("ROSCRIBE_EMBEDDER", "").lower() == "default":
        return None, "default"
    try:
        import sentence_transformers  # noqa: F401
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

        return SentenceTransformerEmbeddingFunction(model_name=settings.embedding_model), "bge_m3"
    except Exception:
        return None, "default"  # Chroma default: all-MiniLM-L6-v2 (ONNX, English)


_EF, _TAG = _embedding_function()
COLLECTION = f"judgements_{_TAG}"


def get_collection():
    client = chromadb.PersistentClient(path=settings.chroma_dir)
    kwargs = {"name": COLLECTION, "metadata": {"hnsw:space": "cosine"}}
    if _EF is not None:
        kwargs["embedding_function"] = _EF
    return client.get_or_create_collection(**kwargs)


def init_db() -> sqlite3.Connection:
    Path(settings.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(settings.sqlite_path)
    con.execute(
        """CREATE TABLE IF NOT EXISTS judgements (
            case_no TEXT, filename TEXT PRIMARY KEY, date TEXT, parties TEXT,
            judges TEXT, keywords TEXT, legislation TEXT, pdf_url TEXT,
            local_path TEXT, n_chunks INTEGER, indexed_at TEXT)"""
    )
    # Collection-aware index state — survives crashes; correct across embedder switches.
    con.execute(
        """CREATE TABLE IF NOT EXISTS indexed (
            collection TEXT, source TEXT, key TEXT, n_chunks INTEGER, indexed_at TEXT,
            PRIMARY KEY (collection, source, key))"""
    )
    # On-demand breakdown cache.
    con.execute(
        """CREATE TABLE IF NOT EXISTS analyses (
            case_no TEXT PRIMARY KEY, model TEXT, json TEXT, created_at TEXT)"""
    )
    con.commit()
    return con


def is_indexed(con: sqlite3.Connection, key: str, source: str) -> bool:
    """Has this file's chunks already been embedded into the current collection?"""
    return con.execute(
        "SELECT 1 FROM indexed WHERE collection=? AND source=? AND key=?",
        (COLLECTION, source, key),
    ).fetchone() is not None


def mark_indexed(con: sqlite3.Connection, key: str, source: str, n_chunks: int) -> None:
    con.execute(
        "INSERT OR REPLACE INTO indexed (collection, source, key, n_chunks, indexed_at) "
        "VALUES (?,?,?,?,?)",
        (COLLECTION, source, key, n_chunks, datetime.now().isoformat(timespec="seconds")),
    )
    con.commit()


def get_analysis(con: sqlite3.Connection, case_no: str) -> dict | None:
    row = con.execute("SELECT json FROM analyses WHERE case_no=?", (case_no,)).fetchone()
    return json.loads(row[0]) if row else None


def save_analysis(con: sqlite3.Connection, case_no: str, data: dict, model: str) -> None:
    con.execute(
        "INSERT OR REPLACE INTO analyses (case_no, model, json, created_at) VALUES (?,?,?,?)",
        (case_no, model, json.dumps(data, ensure_ascii=False),
         datetime.now().isoformat(timespec="seconds")),
    )
    con.commit()


def upsert_judgement(con: sqlite3.Connection, meta: dict, n_chunks: int) -> None:
    con.execute(
        """INSERT OR REPLACE INTO judgements
           (case_no, filename, date, parties, judges, keywords, legislation,
            pdf_url, local_path, n_chunks, indexed_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            meta.get("case_no", ""), meta.get("filename", ""), meta.get("date", ""),
            meta.get("parties", ""), json.dumps(meta.get("judges", [])),
            json.dumps(meta.get("keywords", [])), json.dumps(meta.get("legislation", [])),
            meta.get("pdf_url", ""), meta.get("local_path", ""), n_chunks,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    con.commit()


def add_chunks(chunks: list[Chunk], extra_meta: dict | None = None) -> None:
    """Embed and upsert chunks into Chroma (idempotent on chunk id)."""
    if not chunks:
        return
    col = get_collection()
    ids, docs, metas = [], [], []
    for i, c in enumerate(chunks):
        ids.append(f"{c.case_no}|p{c.page}|{i}")
        docs.append(c.text)
        m = {
            "case_no": c.case_no, "page": c.page, "para": c.para or "",
            "source": c.source, "anchor": c.anchor(),
        }
        m.update({k: v for k, v in c.metadata.items() if isinstance(v, (str, int, float, bool))})
        if extra_meta:
            m.update({k: v for k, v in extra_meta.items() if isinstance(v, (str, int, float))})
        metas.append(m)
    col.upsert(ids=ids, documents=docs, metadatas=metas)


def similarity_search(query: str, k: int = 20, source: str | None = None) -> list[dict]:
    col = get_collection()
    where = {"source": source} if source else None
    res = col.query(query_texts=[query], n_results=k, where=where)
    hits = []
    for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
        hits.append({"text": doc, "meta": meta, "distance": dist})
    return hits
