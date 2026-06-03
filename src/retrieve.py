"""Phase 4 — Retrieval + reranking.

Two stages: (1) vector recall from Chroma, (2) BGE-Reranker-v2
(`bge-reranker-v2-m3`, multilingual) re-scores the candidates to prioritise
high-relevance chunks. Retrieves from the judgment corpus first, then the
personal repository (see CLAUDE.md).

TODO (Phase 4): implement rerank + the dual-corpus retrieve.
"""

from __future__ import annotations

from .ingest import Chunk
from .store import similarity_search  # noqa: F401  (used once implemented)


def retrieve(query: str, k: int = 8) -> list[Chunk]:
    """Chroma recall -> bge-reranker-v2 -> top-k (judgments first, then notes)."""
    raise NotImplementedError("Phase 4: recall -> bge-reranker-v2 -> top-k.")
