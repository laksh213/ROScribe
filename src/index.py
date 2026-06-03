"""Build the index: extract + chunk every downloaded PDF, store in SQLite + Chroma.

Joins each PDF with its row in data/manifest.json (case no, date, parties, judges,
keywords, legislation) so the metadata store is rich from the start.

CLI:
  python -m src.index            # index everything in data/sc_judgements/
  python -m src.index --limit 5  # first 5 only
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import store
from .config import REPO_ROOT, settings
from .ingest import case_no_from_filename, chunk_pages, extract_pages

JUDGEMENTS_DIR = REPO_ROOT / "data" / "sc_judgements"
MANIFEST = REPO_ROOT / "data" / "manifest.json"


def load_manifest() -> dict[str, dict]:
    """Map local PDF filename -> manifest record."""
    if not MANIFEST.exists():
        return {}
    out: dict[str, dict] = {}
    for r in json.loads(MANIFEST.read_text()):
        lp = r.get("local_path")
        if lp:
            out[Path(lp).name] = r
    return out


def build(limit: int | None = None) -> None:
    con = store.init_db()
    meta_by_file = load_manifest()
    pdfs = sorted(JUDGEMENTS_DIR.glob("*.pdf"))
    if limit:
        pdfs = pdfs[:limit]

    print(f"Indexing {len(pdfs)} judgements into {store.COLLECTION} ...")
    for p in pdfs:
        meta = dict(meta_by_file.get(p.name, {}))
        case_no = meta.get("case_no") or case_no_from_filename(p.name)
        pages = extract_pages(str(p), ocr_langs=settings.tesseract_langs)
        chunks = chunk_pages(pages, case_no)
        store.add_chunks(chunks, extra_meta={"date": meta.get("date", ""), "filename": p.name})
        meta.update({"filename": p.name, "case_no": case_no, "local_path": str(p)})
        store.upsert_judgement(con, meta, len(chunks))
        print(f"  {case_no:30} {len(pages):>2}p  {len(chunks):>3} chunks")

    print(f"\nDone. SQLite: {settings.sqlite_path}\n      Chroma:  {settings.chroma_dir}  ({store.COLLECTION})")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Build the ROScribe index.")
    ap.add_argument("--limit", type=int, default=None)
    build(ap.parse_args(argv).limit)


if __name__ == "__main__":
    main()
