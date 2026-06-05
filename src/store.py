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


def _embedder_tag() -> str:
    """Which embedder/collection — computed WITHOUT loading the model."""
    if os.getenv("ROSCRIBE_EMBEDDER", "").lower() == "default":
        return "default"
    try:
        import sentence_transformers  # noqa: F401

        return "bge_m3"
    except Exception:
        return "default"


_TAG = _embedder_tag()
COLLECTION = f"judgements_{_TAG}"
_EF = None  # the heavy model is loaded lazily, only when actually embedding


def _get_ef():
    global _EF
    if _EF is None and _TAG == "bge_m3":
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

        _EF = SentenceTransformerEmbeddingFunction(model_name=settings.embedding_model)
    return _EF  # None → Chroma's built-in default embedder


def get_collection():
    client = chromadb.PersistentClient(path=settings.chroma_dir)
    kwargs = {"name": COLLECTION, "metadata": {"hnsw:space": "cosine"}}
    ef = _get_ef()
    if ef is not None:
        kwargs["embedding_function"] = ef
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


# --------------------- keyword / full-text search ------------------------ #
def build_fts(collection_name: str = "judgements_bge_m3", rebuild: bool = False) -> None:
    """One-time: build a SQLite FTS5 index over chunk text for keyword search.

    Reads documents straight from Chroma (no embedding model needed)."""
    import chromadb

    con = sqlite3.connect(settings.sqlite_path)
    if rebuild:
        con.execute("DROP TABLE IF EXISTS chunks_fts")
    con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(case_no, source, page UNINDEXED, text)")
    con.commit()
    if con.execute("SELECT count(*) FROM chunks_fts").fetchone()[0] and not rebuild:
        print("FTS already built."); con.close(); return

    col = chromadb.PersistentClient(path=settings.chroma_dir).get_collection(collection_name)
    total = col.count()
    print(f"Building FTS over {total} chunks from {collection_name} …", flush=True)
    BATCH, done = 5000, 0
    for off in range(0, total, BATCH):
        res = col.get(include=["documents", "metadatas"], limit=BATCH, offset=off)
        rows = [
            (m.get("case_no", ""), m.get("source", ""), str(m.get("page", "")), d or "")
            for d, m in zip(res["documents"], res["metadatas"])
        ]
        con.executemany("INSERT INTO chunks_fts (case_no, source, page, text) VALUES (?,?,?,?)", rows)
        con.commit()
        done += len(rows)
        print(f"  {done}/{total}", flush=True)
    con.close()
    print("FTS built.", flush=True)


def keyword_search(query: str, limit: int = 60) -> list[dict]:
    """Exact/keyword search: judge & party names + official keywords (metadata)
    plus full-text phrase matches in the judgment text. Returns judgements."""
    import re

    q = (query or "").strip()
    if not q:
        return []
    con = sqlite3.connect(settings.sqlite_path)
    results: dict[str, dict] = {}
    like = f"%{q}%"
    for cn, date, parties in con.execute(
        "SELECT case_no, date, parties FROM judgements "
        "WHERE case_no LIKE ? OR parties LIKE ? OR judges LIKE ? OR keywords LIKE ? OR legislation LIKE ? "
        "ORDER BY date DESC LIMIT ?",
        (like, like, like, like, like, limit),
    ):
        results[cn] = {"case_no": cn, "date": date or "", "snippet": (parties or "")[:110], "why": "metadata"}

    tokens = re.findall(r"[A-Za-z0-9]+", q)
    if tokens:
        try:
            for cn, date, snip in con.execute(
                "SELECT j.case_no, j.date, snippet(chunks_fts, 3, '«', '»', '…', 12) "
                "FROM chunks_fts f JOIN judgements j ON j.case_no = f.case_no "
                "WHERE chunks_fts MATCH ? LIMIT ?",
                (" ".join(tokens), limit * 4),
            ):
                results.setdefault(cn, {"case_no": cn, "date": date or "", "snippet": snip, "why": "text"})
        except Exception:
            pass
    con.close()
    meta = sorted((r for r in results.values() if r["why"] == "metadata"), key=lambda r: r["date"], reverse=True)
    text = sorted((r for r in results.values() if r["why"] == "text"), key=lambda r: r["date"], reverse=True)
    return (meta + text)[:limit]


# Curated legal-area taxonomy (real practice areas) -> case-no prefixes + the
# legal keywords that identify each area in the judgment text.
LEGAL_AREAS: dict[str, dict] = {
    "Fundamental Rights": {"prefix": ["SC/FR", "SC FR"], "terms": ["fundamental rights", "article 12", "article 126", "article 14", "equal protection"]},
    "Constitutional & Administrative": {"terms": ["writ of certiorari", "mandamus", "judicial review", "ultra vires", "natural justice", "legitimate expectation"]},
    "Labour & Employment": {"terms": ["labour tribunal", "termination of employment", "reinstatement", "industrial dispute", "workman", "unfair dismissal", "compensation in lieu"]},
    "Land & Property": {"terms": ["title to land", "ejectment", "deed of transfer", "co-owner", "encroachment", "declaration of title"]},
    "Partition": {"terms": ["partition action", "partition", "co-owners", "preliminary plan"]},
    "Prescription & Laches": {"terms": ["prescription", "laches", "adverse possession", "prescriptive title"]},
    "Trusts": {"terms": ["constructive trust", "resulting trust", "fiduciary", "trustee", "trust property"]},
    "Testamentary & Probate": {"terms": ["last will", "executor", "administrator", "intestate", "probate", "letters of administration"]},
    "Contract": {"terms": ["breach of contract", "consideration", "specific performance", "agreement to sell", "rescission"]},
    "Delict & Negligence": {"terms": ["negligence", "delict", "duty of care", "damages", "vicarious liability"]},
    "Defamation": {"terms": ["defamation", "libel", "slander"]},
    "Criminal Law & Procedure": {"terms": ["indictment", "penal code", "criminal procedure", "conviction", "culpable homicide", "sentence"]},
    "Bail": {"terms": ["bail", "remand", "anticipatory bail"]},
    "Evidence": {"terms": ["burden of proof", "admissibility", "evidence ordinance", "hearsay", "circumstantial evidence", "dock identification"]},
    "Civil Procedure": {"terms": ["civil procedure code", "summons", "plaint", "interlocutory", "summary procedure", "default judgment"]},
    "Commercial & Company": {"prefix": ["SC/CHC", "SC CHC"], "terms": ["company", "shares", "winding up", "director", "commercial high court", "shareholder"]},
    "Banking & Finance": {"terms": ["mortgage", "promissory note", "guarantee", "recovery of loans", "parate execution", "hypothecary"]},
    "Tax & Revenue": {"terms": ["income tax", "value added tax", "customs", "revenue", "tax assessment"]},
    "Intellectual Property": {"terms": ["trademark", "patent", "copyright", "passing off", "infringement"]},
    "Family & Matrimonial": {"terms": ["matrimonial", "divorce", "maintenance", "custody", "matrimonial home", "judicial separation"]},
    "Tenancy & Rent": {"terms": ["rent act", "tenant", "premises", "ejectment of tenant", "controlled premises"]},
    "Election Law": {"terms": ["election petition", "election", "franchise", "polling"]},
    "Bribery & Corruption": {"terms": ["bribery", "corruption", "commission to investigate allegations"]},
    "Arbitration": {"terms": ["arbitration", "arbitral award", "arbitration act"]},
    "Insurance": {"terms": ["insurance", "insurer", "policy of insurance", "indemnity"]},
    "Citizenship & Immigration": {"terms": ["citizenship", "immigration", "passport", "emigration"]},
    "Writ Applications": {"terms": ["writ", "certiorari", "mandamus", "prohibition", "quo warranto"]},
}


def area_search(area: str, limit: int = 120) -> list[dict]:
    """Cases for a curated legal area — by case-no prefix and/or FTS keywords."""
    spec = LEGAL_AREAS.get(area)
    if not spec:
        return []
    con = sqlite3.connect(settings.sqlite_path)
    results: dict[str, dict] = {}
    for pfx in spec.get("prefix", []):
        for cn, date, parties in con.execute(
            "SELECT case_no, date, parties FROM judgements WHERE case_no LIKE ? ORDER BY date DESC LIMIT ?",
            (pfx + "%", limit),
        ):
            results[cn] = {"case_no": cn, "date": date or "", "snippet": (parties or "")[:100]}
    if spec.get("terms"):
        fts_q = " OR ".join(f'"{t}"' for t in spec["terms"])
        try:
            for cn, date, snip in con.execute(
                "SELECT j.case_no, j.date, snippet(chunks_fts, 3, '«', '»', '…', 12) "
                "FROM chunks_fts f JOIN judgements j ON j.case_no = f.case_no "
                "WHERE chunks_fts MATCH ? LIMIT ?",
                (fts_q, limit * 4),
            ):
                results.setdefault(cn, {"case_no": cn, "date": date or "", "snippet": snip})
        except Exception:
            pass
    con.close()
    return sorted(results.values(), key=lambda r: r["date"], reverse=True)[:limit]
