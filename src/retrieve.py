"""Phase 4 — Retrieval + reranking.

Two stages: (1) vector recall from Chroma, (2) BGE-Reranker-v2
(`bge-reranker-v2-m3`, multilingual) re-scores the candidates. The reranker is
optional — if FlagEmbedding isn't installed yet, recall falls back to pure vector
order so the pipeline still runs.

CLI:
  python -m src.retrieve "compensation in lieu of reinstatement" -k 5
"""

from __future__ import annotations

import argparse

from .config import settings
from .store import similarity_search

_RERANKER = None


def _get_reranker():
    global _RERANKER
    if _RERANKER is None:
        from FlagEmbedding import FlagReranker  # heavy; imported lazily

        _RERANKER = FlagReranker(settings.reranker_model, use_fp16=True)
    return _RERANKER


def _rerank(query: str, hits: list[dict], k: int) -> list[dict]:
    try:
        reranker = _get_reranker()
        scores = reranker.compute_score([[query, h["text"]] for h in hits])
        for h, s in zip(hits, scores):
            h["rerank"] = float(s)
        hits = sorted(hits, key=lambda h: h["rerank"], reverse=True)
    except Exception:
        pass  # reranker unavailable -> keep vector order
    return hits[:k]


def retrieve(query: str, k: int = 8, source: str | None = None) -> list[dict]:
    """Chroma recall -> (optional) bge-reranker-v2 -> top-k."""
    hits = similarity_search(query, k=max(k * 3, 20), source=source)
    if settings.use_reranker:
        return _rerank(query, hits, k)
    return hits[:k]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Semantic search over the index.")
    ap.add_argument("query")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--source", choices=["judgment", "personal_repo"], default=None,
                    help="restrict to judgements or your notes")
    args = ap.parse_args(argv)

    hits = retrieve(args.query, args.k, source=args.source)
    if not hits:
        print("No results — is the index built? Run: python -m src.index")
        return
    for h in hits:
        m = h["meta"]
        score = h.get("rerank", -h["distance"])
        print(f"\n {m.get('anchor', '?')}   (score {score:.3f})")
        print("  " + h["text"][:260].strip().replace(chr(10), " ") + "…")


if __name__ == "__main__":
    main()
