"""Build the index.

Judgements: extract + chunk every downloaded PDF, join with data/manifest.json
metadata, store in SQLite + Chroma.

Personal repository: walk your notes folder, tag by Subject/Category, store the
chunks in the same Chroma collection under source="personal_repo".

CLI:
  python -m src.index                          # index downloaded judgements
  python -m src.index --limit 5                # first 5 judgements
  python -m src.index --notes "/path/to/notes" # index your law notes
  python -m src.index --notes "/path" --limit 30
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import store
from .config import REPO_ROOT, settings
from .ingest import case_no_from_filename, chunk_pages, extract_pages, load_personal_repo

JUDGEMENTS_DIR = REPO_ROOT / "data" / "sc_judgements"
MANIFEST = REPO_ROOT / "data" / "manifest.json"


def load_manifest() -> dict[str, dict]:
    if not MANIFEST.exists():
        return {}
    out: dict[str, dict] = {}
    for r in json.loads(MANIFEST.read_text()):
        lp = r.get("local_path")
        if lp:
            out[Path(lp).name] = r
    return out


def build_judgements(limit: int | None = None) -> None:
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
        print(f"  {case_no:30} {len(pages):>3}p  {len(chunks):>4} chunks")
    print(f"\nDone. SQLite: {settings.sqlite_path}\n      Chroma:  {settings.chroma_dir}  ({store.COLLECTION})")


def build_notes(directory: str, limit: int | None = None) -> None:
    store.init_db()
    print(f"Loading personal repository: {directory}")
    chunks = load_personal_repo(directory, limit=limit)
    subjects: dict[str, int] = {}
    for c in chunks:
        subjects[c.metadata.get("subject", "?")] = subjects.get(c.metadata.get("subject", "?"), 0) + 1

    BATCH = 256
    for i in range(0, len(chunks), BATCH):
        store.add_chunks(chunks[i : i + BATCH])
    print(f"Indexed {len(chunks)} note chunks into {store.COLLECTION} (source=personal_repo)")
    for s, n in sorted(subjects.items()):
        print(f"  {s:40} {n:>5} chunks")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Build the ROScribe index.")
    ap.add_argument("--notes", type=str, default=None, help="index a personal-notes folder")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)
    if args.notes:
        build_notes(args.notes, args.limit)
    else:
        build_judgements(args.limit)


if __name__ == "__main__":
    main()
