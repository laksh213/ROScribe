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
import re
import sqlite3
import threading
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
_EF_LOCK = threading.RLock()  # two early callers must not both load the model
_COLLECTION_CACHE = None
_EMBEDDER_READY = False  # flipped by warm_embedder(); semantic search waits for it


def _get_ef():
    global _EF
    with _EF_LOCK:
        if _EF is None and _TAG == "bge_m3":
            from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

            _EF = SentenceTransformerEmbeddingFunction(model_name=settings.embedding_model)
        return _EF  # None → Chroma's built-in default embedder


def get_collection():
    global _COLLECTION_CACHE
    if _COLLECTION_CACHE is not None:
        return _COLLECTION_CACHE
    with _EF_LOCK:
        if _COLLECTION_CACHE is None:
            client = chromadb.PersistentClient(path=settings.chroma_dir)
            kwargs = {"name": COLLECTION, "metadata": {"hnsw:space": "cosine"}}
            ef = _get_ef()
            if ef is not None:
                kwargs["embedding_function"] = ef
            _COLLECTION_CACHE = client.get_or_create_collection(**kwargs)
    return _COLLECTION_CACHE


def embedder_ready() -> bool:
    return _EMBEDDER_READY


def warm_embedder() -> bool:
    """Load bge-m3 + the Chroma collection once (~10-20 s) so semantic search is
    instant afterwards. Safe to call from a background thread at app startup."""
    global _EMBEDDER_READY
    if _TAG != "bge_m3":
        return False
    if _EMBEDDER_READY:
        return True
    try:
        similarity_search("warm up", k=1)
        _EMBEDDER_READY = True
        return True
    except Exception as e:  # noqa: BLE001 — non-fatal: search degrades to FTS-only
        print(f"[store] embedder warm-up failed: {e}")
        return False


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


def fts_index_cases(case_nos: list[str], collection_name: str | None = None) -> int:
    """Incrementally add (or refresh) FTS rows for specific cases — used by the
    monthly corpus update so new judgements become keyword-searchable without a
    full rebuild over the whole corpus. Idempotent: existing rows for a case are
    replaced. Reads chunk text straight from Chroma (no embedding model loaded).
    Returns the number of chunk rows written."""
    if not case_nos:
        return 0
    name = collection_name or COLLECTION
    con = sqlite3.connect(settings.sqlite_path)
    con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(case_no, source, page UNINDEXED, text)")
    con.commit()
    try:
        col = chromadb.PersistentClient(path=settings.chroma_dir).get_collection(name)
    except Exception as e:  # noqa: BLE001 — collection missing → nothing to index
        print(f"[fts] collection {name!r} unavailable: {e}")
        con.close()
        return 0
    added = 0
    for cn in case_nos:
        con.execute("DELETE FROM chunks_fts WHERE case_no=?", (cn,))
        res = col.get(where={"case_no": cn}, include=["documents", "metadatas"])
        docs, metas = res.get("documents") or [], res.get("metadatas") or []
        rows = [
            (m.get("case_no", ""), m.get("source", ""), str(m.get("page", "")), d or "")
            for d, m in zip(docs, metas)
        ]
        if rows:
            con.executemany("INSERT INTO chunks_fts (case_no, source, page, text) VALUES (?,?,?,?)", rows)
            added += len(rows)
    con.commit()
    con.close()
    return added


# --- query understanding: acronyms, stopwords, tiered FTS ----------------- #

# Common Sri Lankan legal acronyms <-> their expansions. Queries are expanded in
# BOTH directions ("RDA" also finds "Road Development Authority" and vice versa)
# because judgments switch freely between the two forms. Extend as needed.
LEGAL_ACRONYMS: dict[str, list[str]] = {
    "rda": ["road development authority"],
    "uda": ["urban development authority"],
    "ceb": ["ceylon electricity board"],
    "cpc": ["ceylon petroleum corporation", "civil procedure code"],
    "slpa": ["sri lanka ports authority"],
    "nwsdb": ["national water supply and drainage board"],
    "boi": ["board of investment"],
    "cbsl": ["central bank of sri lanka"],
    "epf": ["employees provident fund"],
    "etf": ["employees trust fund"],
    "ag": ["attorney general"],
    "igp": ["inspector general of police"],
    "oic": ["officer in charge"],
    "cid": ["criminal investigation department"],
    "fcid": ["financial crimes investigation division"],
    "tid": ["terrorist investigation division"],
    "pta": ["prevention of terrorism act"],
    "iccpr": ["international covenant on civil and political rights"],
    "nic": ["national identity card"],
    "rti": ["right to information"],
    "hrcsl": ["human rights commission"],
    "hrc": ["human rights commission"],
    "jsc": ["judicial service commission"],
    "psc": ["public service commission"],
    "nsb": ["national savings bank"],
    "boc": ["bank of ceylon"],
    "slic": ["sri lanka insurance"],
    "sltb": ["sri lanka transport board"],
    "ctb": ["ceylon transport board"],
    "cmc": ["colombo municipal council"],
    "cea": ["central environmental authority"],
    "mepa": ["marine environment protection authority"],
    "ugc": ["university grants commission"],
    "slmc": ["sri lanka medical council"],
    "trc": ["telecommunications regulatory commission"],
    "caa": ["consumer affairs authority"],
    "vat": ["value added tax"],
    "ltte": ["liberation tigers of tamil eelam"],
    "slas": ["sri lanka administrative service"],
}

# Words that carry no signal in a case search ("cases involving the RDA").
# Loose tokens matching these are dropped; quoted phrases are never touched.
_QUERY_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "by", "can", "could", "did",
    "do", "does", "for", "from", "had", "has", "have", "he", "her", "his", "how",
    "i", "if", "in", "into", "is", "it", "its", "me", "my", "no", "not", "of",
    "on", "or", "our", "s", "she", "should", "so", "such", "than", "that", "the",
    "their", "them", "then", "there", "these", "they", "this", "those", "to",
    "under", "up", "upon", "was", "we", "were", "what", "when", "where", "which",
    "who", "whose", "why", "will", "with", "would", "you", "your",
    "case", "cases", "involving", "involve", "involved", "involves", "related",
    "relating", "relate", "regarding", "concerning", "concern", "about", "matter",
    "matters", "any", "all", "find", "show", "search", "judgment", "judgments",
    "judgement", "judgements", "decision", "decisions",
}

_ACRO_NGRAMS: dict[tuple[str, ...], str] | None = None  # expansion tokens -> acronym


def _tokenize(text: str) -> list[str]:
    """Unicode-aware tokens (keeps Sinhala/Tamil — FTS5 unicode61 indexes them)."""
    return [t.lower() for t in re.findall(r"\w+", text or "")]


def _acro_ngrams() -> dict[tuple[str, ...], str]:
    global _ACRO_NGRAMS
    if _ACRO_NGRAMS is None:
        _ACRO_NGRAMS = {}
        for acro, exps in LEGAL_ACRONYMS.items():
            for e in exps:
                _ACRO_NGRAMS[tuple(_tokenize(e))] = acro
    return _ACRO_NGRAMS


def _query_units(tokens: list[str]) -> list[list[str]]:
    """Collapse the token stream into search units (each a list of equivalent
    variants): known entity phrases become [phrase, acronym], acronyms expand to
    [acronym, *expansions], plain tokens stay single. Stopwords drop out."""
    ngrams = _acro_ngrams()
    max_n = max((len(k) for k in ngrams), default=1)
    units: list[list[str]] = []
    i = 0
    while i < len(tokens):
        hit = None
        for n in range(min(max_n, len(tokens) - i), 1, -1):
            acro = ngrams.get(tuple(tokens[i:i + n]))
            if acro:
                hit = (n, acro)
                break
        if hit:
            n, acro = hit
            units.append([" ".join(tokens[i:i + n]), acro])
            i += n
            continue
        t = tokens[i]
        if t in LEGAL_ACRONYMS:
            units.append([t, *LEGAL_ACRONYMS[t]])
        elif t not in _QUERY_STOPWORDS:
            units.append([t])
        i += 1
    if not units:  # the whole query was stopwords — search it literally
        units = [[t] for t in tokens]
    return units


def _fts_group(variants: list[str], prefix: bool = False) -> str:
    """One unit -> FTS5 syntax: ("rda" OR "road development authority")."""
    star = "*" if prefix else ""
    parts = [f'"{v}"{star}' for v in variants]
    return "(" + " OR ".join(parts) + ")" if len(parts) > 1 else parts[0]


def _fts_queries(query: str) -> list[tuple[str, str]]:
    """Translate a natural-language query into tiered FTS5 MATCH strings, tried
    in order: ("phrase", …) exact phrases → ("all", …) every term anywhere in a
    chunk → ("any", …) at least one term (last-resort, only used when the
    stricter tiers return nothing). Honours "quoted phrases", drops query noise
    ("cases involving the…"), and expands acronyms in both directions."""
    q = (query or "").replace("“", '"').replace("”", '"').strip()
    if not q:
        return []
    quoted = [p.strip() for p in re.findall(r'"([^"]+)"', q) if p.strip()]
    rest = re.sub(r'"[^"]*"?', " ", q)
    tokens = _tokenize(rest)
    units = _query_units(tokens) if tokens else []

    groups: list[list[str]] = []
    for ph in quoted:  # quoted phrases kept verbatim (plus acronym variant if known)
        key = tuple(_tokenize(ph))
        if not key:
            continue
        acro = _acro_ngrams().get(key)
        groups.append([" ".join(key), acro] if acro else [" ".join(key)])
    groups += units
    if not groups:
        return []

    # While the user is mid-word, prefix-match the last term ("bunker fu" works).
    # Single characters are not starred — "r"* would expand to a huge term set.
    star_last = bool(units) and bool(tokens) and len(tokens[-1]) >= 2 \
        and bool(re.search(r"\w$", q)) and units[-1][0].split(" ")[-1] == tokens[-1]

    def render(gs: list[list[str]], op: str, star: bool) -> str:
        return f" {op} ".join(
            _fts_group(g, prefix=(star and i == len(gs) - 1)) for i, g in enumerate(gs)
        )

    # Tier 1: runs of consecutive plain tokens become exact phrases
    # ("bunker fuel related cases" -> "bunker fuel").
    t1_groups: list[list[str]] = [g for g in groups[: len(groups) - len(units)]]
    run: list[str] = []

    def _flush_run():
        if len(run) >= 2:
            t1_groups.append([" ".join(run)])
        elif run:
            t1_groups.append([run[0]])
        run.clear()

    for u in units:
        if len(u) == 1 and " " not in u[0]:
            run.append(u[0])
        else:
            _flush_run()
            t1_groups.append(u)
    _flush_run()

    t2 = render(groups, "AND", star_last)
    t1 = render(t1_groups, "AND", False)
    tiers: list[tuple[str, str]] = []
    if t1 != t2:
        tiers.append(("phrase", t1))
    tiers.append(("all", t2))
    if len(groups) > 1:
        tiers.append(("any", render(groups, "OR", star_last)))
    return tiers


_WHY_TIER = {"metadata": 0, "phrase": 1, "text": 2, "broad": 3, "semantic": 4}


def _date_key(d: str) -> int:
    digits = re.sub(r"\D", "", (d or "")[:10])
    return int(digits) if digits else 0


def _rank_key(h: dict) -> tuple:
    """Sort: tier (metadata → phrase → all-terms → broad → semantic), then
    relevance (bm25/distance — lower is better), then newest first."""
    return (h.get("tier", 9), h.get("score", 0.0), -_date_key(h.get("date", "")))


def _metadata_variants(query: str) -> list[str]:
    """Strings to LIKE against metadata: the raw query plus acronym expansions
    (so "RDA" also matches parties named "Road Development Authority")."""
    out = [query]
    toks = _tokenize(query)
    if len(toks) == 1 and toks[0] in LEGAL_ACRONYMS:
        out += LEGAL_ACRONYMS[toks[0]]
    acro = _acro_ngrams().get(tuple(toks))
    if acro:
        out.append(acro)
    return out[:6]


def _query_case_hits(con: sqlite3.Connection, query: str, per_tier: int = 400) -> dict[str, dict]:
    """The one engine behind keyword/combined search. Returns
    {case_no: {tier, score, hits, snippet, date, why}} — metadata LIKE matches
    plus tiered FTS matches ranked by bm25, best matching chunk as the snippet."""
    q = (query or "").strip()
    out: dict[str, dict] = {}
    if not q:
        return out

    for v in _metadata_variants(q):
        like = f"%{v}%"
        # Substring LIKE on a short token ("RDA" in "Jayawardana") is noise —
        # short single words get a word-boundary check instead.
        boundary = re.compile(rf"\b{re.escape(v)}", re.IGNORECASE) if (len(v) < 6 and " " not in v) else None
        for cn, date, parties, judges, kws, leg in con.execute(
            "SELECT case_no, date, parties, judges, keywords, legislation FROM judgements "
            "WHERE case_no LIKE ? OR parties LIKE ? OR judges LIKE ? OR keywords LIKE ? OR legislation LIKE ? "
            "ORDER BY date DESC LIMIT ?",
            (like, like, like, like, like, per_tier),
        ):
            if boundary and not boundary.search(" ".join(filter(None, (cn, parties, judges, kws, leg)))):
                continue
            out.setdefault(cn, {"tier": 0, "score": 0.0, "hits": 1, "why": "metadata",
                                "snippet": (parties or "")[:110], "date": date or ""})

    for why, match in _fts_queries(q):
        if why == "any" and out:
            break  # broad OR-matching only when nothing stricter matched
        tier_why = {"phrase": "phrase", "all": "text", "any": "broad"}[why]
        try:
            # bm25()/snippet() must run in the FTS row context, and the inner
            # LIMIT stops SQLite flattening the subquery into the aggregate
            # (which raises "unable to use function bm25 in the requested
            # context"). min(score) keeps the best chunk's snippet per case.
            rows = con.execute(
                "SELECT sub.case_no, j.date, sub.snip, count(*), min(sub.score) AS best "
                "FROM ("
                "  SELECT case_no, snippet(chunks_fts, 3, '«', '»', '…', 12) AS snip, "
                "         bm25(chunks_fts) AS score "
                "  FROM chunks_fts WHERE chunks_fts MATCH ? LIMIT 20000"
                ") sub JOIN judgements j ON j.case_no = sub.case_no "
                "GROUP BY sub.case_no ORDER BY best LIMIT ?",
                (match, per_tier),
            ).fetchall()
        except sqlite3.OperationalError:  # no FTS table / malformed edge case
            continue
        for cn, date, snip, nhits, score in rows:
            out.setdefault(cn, {"tier": _WHY_TIER[tier_why], "score": float(score or 0.0),
                                "hits": int(nhits), "why": tier_why,
                                "snippet": snip or "", "date": date or ""})
    return out


def semantic_case_hits(query: str, k: int = 40, max_cases: int = 15) -> dict[str, dict]:
    """Embedding-based matches (bge-m3 + Chroma) for concept queries whose words
    differ from the judgment's ("bunker fuel" ≈ "furnace oil"). Returns {} until
    warm_embedder() has run, so it never blocks a search on a cold model."""
    if not _EMBEDDER_READY:
        return {}
    out: dict[str, dict] = {}
    try:
        for h in similarity_search(query, k=k, source="judgment"):
            cn = (h.get("meta") or {}).get("case_no") or ""
            d = float(h.get("distance") or 1.0)
            if not cn or d > 0.65:
                continue
            cur = out.get(cn)
            if cur is None:
                snip = " ".join((h.get("text") or "").split())[:110]
                out[cn] = {"tier": 4, "score": d, "hits": 1, "why": "semantic",
                           "snippet": snip, "date": ""}
            else:
                cur["hits"] += 1
                cur["score"] = min(cur["score"], d)
    except Exception as e:  # noqa: BLE001 — semantic is a bonus, never break search
        print(f"[store] semantic search failed: {e}")
        return {}
    return dict(sorted(out.items(), key=lambda kv: kv[1]["score"])[:max_cases])


def keyword_search(query: str, limit: int = 60) -> list[dict]:
    """Keyword/phrase search over metadata + full judgment text. Understands
    "quoted phrases", drops query noise ("cases involving …"), expands SL legal
    acronyms (RDA ↔ Road Development Authority) and ranks by tier then bm25."""
    q = (query or "").strip()
    if not q:
        return []
    con = sqlite3.connect(settings.sqlite_path)
    hits = _query_case_hits(con, q)
    con.close()
    rows = [{"case_no": cn, "date": h["date"], "snippet": h["snippet"],
             "why": h["why"], "hits": h["hits"]} for cn, h in hits.items()]
    rows.sort(key=lambda r: _rank_key(hits[r["case_no"]]))
    return rows[:limit]


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


_MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December"]


def _year_month_of(case_no: str, date: str) -> tuple[str | None, str | None]:
    """Best-effort (year, month-name) for a judgement: prefer the real `date`
    column, fall back to a 4-digit year embedded in the case number."""
    import re

    y = None
    if date and date[:4].isdigit():
        y = date[:4]
    else:
        yrs = [int(x) for x in re.findall(r"(?:19|20)\d{2}", case_no or "") if 1950 <= int(x) <= 2027]
        if yrs:
            y = str(max(yrs))
    m = None
    if date and len(date) >= 7 and date[5:7].isdigit():
        mi = int(date[5:7])
        if 1 <= mi <= 12:
            m = _MONTH_NAMES[mi - 1]
    return y, m


def _area_case_nos(con: sqlite3.Connection, area: str) -> set[str]:
    """Case numbers for a curated legal area (prefix + FTS terms) — ids only, no
    snippets, so it stays cheap inside an intersected/combined query."""
    spec = LEGAL_AREAS.get(area)
    if not spec:
        return set()
    out: set[str] = set()
    for pfx in spec.get("prefix", []):
        for (cn,) in con.execute("SELECT case_no FROM judgements WHERE case_no LIKE ?", (pfx + "%",)):
            out.add(cn)
    if spec.get("terms"):
        fts_q = " OR ".join(f'"{t}"' for t in spec["terms"])
        try:
            for (cn,) in con.execute("SELECT DISTINCT case_no FROM chunks_fts WHERE chunks_fts MATCH ?", (fts_q,)):
                out.add(cn)
        except Exception:
            pass
    return out


def _query_case_nos(con: sqlite3.Connection, query: str) -> set[str]:
    """Case numbers matching a free-text query across metadata + full text."""
    return set(_query_case_hits(con, query))


def _canonical_justice(name: str) -> str:
    """Collapse spelling variants of one justice to a single key — strips titles
    (Hon./Dr./Justice), trailing silk/suffix (PC, J., C.J.), and punctuation so
    'J.A.N. de Silva CJ' == 'Hon. J.A.N. De Silva, C.J.'."""
    s = " " + (name or "").strip() + " "
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"^\s*(?:the\s+)?(?:hon(?:'?ble|ourable|orable)?\.?\s*)?(?:(?:mr|mrs|ms|dr)\.?\s*)?(?:justice\s+|judge\s+)?", " ", s, flags=re.I)
    s = re.sub(r"[\s,]*(?:p\.?c\.?|q\.?c\.?)?[\s,]*(?:c\.?\s*j\.?|a\.?c\.?j\.?|d\.?c\.?j\.?|j\.?j\.?|j\.?)\s*$", "", s, flags=re.I)
    s = re.sub(r"[\s,]*(?:p\.?c\.?|q\.?c\.?)\s*$", "", s, flags=re.I)
    return re.sub(r"[^a-z0-9]", "", s.lower())


_JUSTICE_GROUPS: dict[str, list[str]] | None = None


def justices_grouped() -> dict[str, list[str]]:
    """Deduped justices: {display_name -> [all raw spelling variants]}. The display
    name is the most frequent (then longest) spelling; filtering matches any variant."""
    global _JUSTICE_GROUPS
    if _JUSTICE_GROUPS is None:
        con = sqlite3.connect(settings.sqlite_path)
        counts: dict[str, int] = {}
        for (j,) in con.execute("SELECT judges FROM judgements WHERE judges IS NOT NULL AND judges!='[]'"):
            try:
                arr = json.loads(j)
            except Exception:
                continue
            for n in arr:
                n = (n or "").strip()
                if n:
                    counts[n] = counts.get(n, 0) + 1
        con.close()
        groups: dict[str, list[tuple[str, int]]] = {}
        for raw, c in counts.items():
            groups.setdefault(_canonical_justice(raw) or raw.lower(), []).append((raw, c))
        _JUSTICE_GROUPS = {
            max(variants, key=lambda rc: (rc[1], len(rc[0])))[0]: [r for r, _ in variants]
            for variants in groups.values()
        }
    return _JUSTICE_GROUPS


def distinct_justices() -> list[str]:
    """Deduped justice display names, alphabetical (one option per justice)."""
    return sorted(justices_grouped().keys(), key=str.lower)


def _judge_case_nos(con, names) -> set[str]:
    """Case numbers for one or more (deduped) justices — OR across the justices and
    each one's spelling variants."""
    groups = justices_grouped()
    out: set[str] = set()
    for nm in names:
        for v in groups.get(nm, [nm]):   # expand a display name to its raw variants
            for (cn,) in con.execute("SELECT case_no FROM judgements WHERE judges LIKE ?", (f"%{v}%",)):
                out.add(cn)
    return out


def combined_search(judge=None, area: str | None = None,
                    year: str | None = None, month: str | None = None,
                    query: str | None = None, semantic: bool = False,
                    limit: int = 200) -> list[dict]:
    """AND-combine any subset of facets — Justice · legal area · year · month ·
    free-text — returning judgements that match *all* supplied facets. With a
    free-text query, results are relevance-ranked (phrase > all-terms > broad)
    with the best matching passage as the snippet; otherwise newest first.
    `semantic=True` additionally merges embedding matches (once the model is warm).

    Each facet contributes a set of case numbers; the result is their
    intersection. An empty facet is ignored; no facets returns []."""
    if isinstance(judge, (list, tuple, set)):
        judge = [str(x).strip() for x in judge if str(x).strip()] or None
    else:
        judge = (judge or "").strip() or None
    area = (area or "").strip() or None
    year = (year or "").strip() or None
    month = (month or "").strip() or None
    query = (query or "").strip() or None
    if not any((judge, area, year, month, query)):
        return []

    con = sqlite3.connect(settings.sqlite_path)
    sets: list[set[str]] = []
    qhits: dict[str, dict] = {}

    if judge:
        names = judge if isinstance(judge, list) else [judge]
        sets.append(_judge_case_nos(con, names))
    if area:
        sets.append(_area_case_nos(con, area))
    if query:
        qhits = _query_case_hits(con, query)
        if semantic:
            for cn, h in semantic_case_hits(query).items():
                qhits.setdefault(cn, h)
        sets.append(set(qhits))
    if year or month:
        ym: set[str] = set()
        for cn, date in con.execute("SELECT case_no, date FROM judgements"):
            yy, mm = _year_month_of(cn, date or "")
            if year and yy != year:
                continue
            if month and mm != month:
                continue
            ym.add(cn)
        sets.append(ym)

    common = set.intersection(*sets) if sets else set()
    if not common:
        con.close()
        return []

    # One cheap full scan for display metadata (table is ~3.8k rows; this avoids
    # SQLite's bound-variable limit that a big IN-clause would hit).
    rows = con.execute("SELECT case_no, date, parties FROM judgements").fetchall()
    con.close()
    out = []
    for cn, d, p in rows:
        if cn not in common:
            continue
        h = qhits.get(cn)
        out.append({"case_no": cn, "date": d or "",
                    "snippet": (h.get("snippet") or (p or "")[:110]) if h else (p or "")[:110],
                    "why": h.get("why", "") if h else "", "hits": h.get("hits", 0) if h else 0})
    if qhits:
        out.sort(key=lambda r: _rank_key(qhits[r["case_no"]]) if r["case_no"] in qhits
                 else (9, 0.0, -_date_key(r["date"])))
    else:
        out.sort(key=lambda r: r["date"], reverse=True)
    return out[:limit]


# --- citation resolution: link a precedent citation to a corpus case_no ------ #
_CN_NORM: dict[str, str] = {}            # normalized case_no -> case_no
_CN_NUMYEAR: dict[str, list[str]] = {}   # "number/year4" -> [case_no, ...]


def _norm_alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _case_signatures(s: str) -> list[tuple[str, str]]:
    """All (number, 4-digit year) pairs in a string. Handles the citation
    variants that broke naive substring matching:
      'SC/FR/272/2016'           -> [('272','2016')]
      'SC FR Application 272/2016'-> [('272','2016')]   (the 'Application' token)
      'SC FR 446 19'             -> [('446','2019')]    (space sep, 2-digit year)
    """
    out: list[tuple[str, str]] = []
    for m in re.finditer(r"(\d{1,4})\s*[/\- ]\s*(\d{2,4})", s or ""):
        num, yr = m.group(1), m.group(2)
        yr4 = yr if len(yr) == 4 else (("20" if int(yr) < 50 else "19") + yr)
        out.append((num, yr4))
    return out


def _ensure_cite_index() -> None:
    global _CN_NORM, _CN_NUMYEAR
    if _CN_NORM:
        return
    con = sqlite3.connect(settings.sqlite_path)
    norm: dict[str, str] = {}
    numyear: dict[str, list[str]] = {}
    for (cn,) in con.execute("SELECT case_no FROM judgements WHERE case_no IS NOT NULL"):
        nk = _norm_alnum(cn)
        if nk:
            norm.setdefault(nk, cn)
        for num, yr4 in _case_signatures(cn):
            numyear.setdefault(f"{num}/{yr4}", []).append(cn)
    con.close()
    _CN_NORM, _CN_NUMYEAR = norm, numyear


def resolve_citation(cited: str) -> str | None:
    """Resolve a precedent citation to a corpus case_no using the CASE NUMBER —
    the only reliable identifier. Tries exact normalized match, then number/year
    (confirmed by court-prefix letters when several cases share a number), then a
    literal bare-case_no substring.

    It deliberately does NOT guess by party name: Sri Lankan surnames recur across
    many cases, so party matching yields confident *wrong* links (e.g. a
    'Tilakaratne v Ariyaratne' citation matching an unrelated case that merely
    shares both surnames). Number-less citations are better handled in the UI as a
    search the user resolves."""
    _ensure_cite_index()
    norm = _norm_alnum(cited)
    if not norm:
        return None
    if norm in _CN_NORM:
        return _CN_NORM[norm]
    for num, yr4 in _case_signatures(cited):
        cns = _CN_NUMYEAR.get(f"{num}/{yr4}")
        if not cns:
            continue
        if len(cns) == 1:
            return cns[0]
        for cn in cns:  # several cases share this number/year -> confirm by court prefix
            pref = re.sub(r"[^a-z]", "", cn.lower())
            if pref and pref in norm:
                return cn
    for k, cn in _CN_NORM.items():  # citation literally contains a bare case_no
        if len(k) >= 9 and k in norm:
            return cn
    return None


def citation_search_terms(cited: str) -> str:
    """Party-name portion of a citation, used for a fallback library search when
    it can't be confidently resolved (the user picks the right case from results).
    Strips court tokens, the number/year, and the 'v' separator."""
    s = re.sub(r"\b(SC|CA|HC|FR|CHC|APN|APPEAL|APPLICATION|No)\b\.?", " ", cited or "", flags=re.I)
    s = re.sub(r"\d{1,4}\s*[/\- ]\s*\d{2,4}", " ", s)
    s = re.sub(r"\bv[s]?\.?\b", " ", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip()
