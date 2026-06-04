"""Build the index — resumable, idempotent, error-tolerant (built for the full corpus).

Judgements: extract + chunk every downloaded PDF, join with manifest metadata,
store in SQLite + Chroma. Personal repo: walk the notes folder, tag by
Subject/Category, store under source="personal_repo".

Re-runs skip files already embedded into the *current* collection (so switching
embedders re-indexes correctly, and a crashed run resumes where it stopped).
A single broken/huge/scanned file is logged and skipped, never fatal.

CLI:
  python -m src.index                          # index downloaded judgements (resume)
  python -m src.index --force                  # re-index everything
  python -m src.index --notes "/path/to/notes" # index your law notes (resume)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import store
from .config import REPO_ROOT, settings
from .ingest import (
    case_no_from_filename,
    chunk_pages,
    chunks_for_note,
    extract_pages,
    list_note_files,
)

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


def build_judgements(limit: int | None = None, force: bool = False) -> None:
    con = store.init_db()
    meta_by_file = load_manifest()
    pdfs = sorted(JUDGEMENTS_DIR.glob("*.pdf"))
    if limit:
        pdfs = pdfs[:limit]

    done = skipped = failed = 0
    print(f"Indexing {len(pdfs)} judgements into {store.COLLECTION} (resume={not force}) …", flush=True)
    for p in pdfs:
        if not force and store.is_indexed(con, p.name, "judgment"):
            skipped += 1
            continue
        try:
            meta = dict(meta_by_file.get(p.name, {}))
            case_no = meta.get("case_no") or case_no_from_filename(p.name)
            pages = extract_pages(str(p), ocr_langs=settings.tesseract_langs)
            chunks = chunk_pages(pages, case_no)
            store.add_chunks(chunks, extra_meta={"date": meta.get("date", ""), "filename": p.name})
            meta.update({"filename": p.name, "case_no": case_no, "local_path": str(p)})
            store.upsert_judgement(con, meta, len(chunks))
            store.mark_indexed(con, p.name, "judgment", len(chunks))
            done += 1
            if done % 25 == 0:
                print(f"  …{done} indexed ({skipped} skipped, {failed} failed)", flush=True)
        except Exception as e:  # noqa: BLE001 — one bad PDF must not kill the run
            failed += 1
            print(f"  SKIP {p.name}: {type(e).__name__}: {e}", flush=True)
    print(f"Judgements done: {done} indexed, {skipped} already-done, {failed} failed.", flush=True)


def build_notes(directory: str, limit: int | None = None, force: bool = False) -> None:
    con = store.init_db()
    files = list_note_files(directory)
    if limit:
        files = files[:limit]

    done = skipped = failed = total_chunks = 0
    print(f"Indexing {len(files)} note files into {store.COLLECTION} (resume={not force}) …", flush=True)
    for p, subject, category in files:
        if not force and store.is_indexed(con, str(p), "personal_repo"):
            skipped += 1
            continue
        try:
            chunks = chunks_for_note(p, subject, category)
            store.add_chunks(chunks)
            store.mark_indexed(con, str(p), "personal_repo", len(chunks))
            total_chunks += len(chunks)
            done += 1
            print(f"  [{done}] {subject}/{category}/{p.name}: {len(chunks)} chunks", flush=True)
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  SKIP {p.name}: {type(e).__name__}: {e}", flush=True)
    print(f"Notes done: {done} files ({total_chunks} chunks), {skipped} already-done, {failed} failed.", flush=True)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Build the ROScribe index (resumable).")
    ap.add_argument("--notes", type=str, default=None, help="index a personal-notes folder")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--force", action="store_true", help="re-index even if already done")
    args = ap.parse_args(argv)
    if args.notes:
        build_notes(args.notes, args.limit, args.force)
    else:
        build_judgements(args.limit, args.force)


if __name__ == "__main__":
    main()
