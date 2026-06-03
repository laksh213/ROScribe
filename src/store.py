"""Phase 3 — Storage (zero-config, local files).

SQLite holds structured metadata (one row per judgement — seeded from
data/manifest.json, enriched with extracted fields) for fast filtering by judge /
date / case_no. ChromaDB holds the embeddings (bge-m3) for semantic search. Both
are plain local files under data/ — no server.

Judgment chunks and personal-repository note chunks share one Chroma collection,
separated by a `source` metadata field.

TODO (Phase 3): init_db (SQLite schema + Chroma collection), upsert_metadata,
embed + add chunks, similarity_search.
"""

from __future__ import annotations

from .ingest import Chunk, Source


def init_db() -> None:
    """Create the SQLite tables and the Chroma collection if absent."""
    raise NotImplementedError("Phase 3: SQLite schema + Chroma collection.")


def upsert_chunks(chunks: list[Chunk]) -> None:
    """Embed chunks (bge-m3) and add/update them in Chroma."""
    raise NotImplementedError("Phase 3: embed + add to Chroma.")


def similarity_search(
    query: str, k: int = 20, source: Source | None = None
) -> list[Chunk]:
    """Vector recall from Chroma, optionally restricted to one corpus."""
    raise NotImplementedError("Phase 3: Chroma query with optional source filter.")
