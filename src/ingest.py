"""Phase 2 — Text extraction & chunking (open source).

Judgements: PyMuPDF (fitz) extracts the text layer fast; if a page has too little
text (scanned), fall back to Tesseract OCR (`eng+sin+tam`). Chunks keep page +
paragraph anchors so citations `[Case No | Page:Para]` stay verifiable.

Personal repository: `load_personal_repo` walks your notes folder (PDF / docx /
txt / md / html), tagging each chunk with Subject and Category derived from the
`NN - Subject / Category / file` folder layout.

CLI:
  python -m src.ingest data/sc_judgements/<file>.pdf --out data/extracted/<file>.md
"""

from __future__ import annotations

import argparse
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import fitz  # PyMuPDF

Source = Literal["judgment", "personal_repo"]

NOTE_EXTS = {".pdf", ".docx", ".txt", ".md", ".html", ".htm"}


@dataclass
class Chunk:
    text: str
    case_no: str
    page: int
    para: str | None = None
    source: Source = "judgment"
    metadata: dict = field(default_factory=dict)  # e.g. {"subject", "category"}

    def anchor(self) -> str:
        if self.para is None:
            return f"[{self.case_no} | p{self.page}]"
        return f"[{self.case_no} | {self.page}:{self.para}]"


# --------------------------------------------------------------------------- #
# Extraction                                                                  #
# --------------------------------------------------------------------------- #
def _ocr_page(page: "fitz.Page", langs: str) -> str:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""
    pix = page.get_pixmap(dpi=300)
    return pytesseract.image_to_string(Image.open(io.BytesIO(pix.tobytes("png"))), lang=langs)


def extract_pages(pdf_path: str, ocr_langs: str = "eng+sin+tam", ocr_threshold: int = 200) -> list[str]:
    """Per-page text via PyMuPDF; OCR pages below `ocr_threshold` chars (0 = never)."""
    pages: list[str] = []
    with fitz.open(pdf_path) as doc:
        for page in doc:
            text = page.get_text("text")
            if len(text.strip()) < ocr_threshold:
                text = _ocr_page(page, ocr_langs) or text
            pages.append(text)
    return pages


def _read_docx(path: str) -> str:
    from docx import Document

    return "\n".join(p.text for p in Document(path).paragraphs if p.text.strip())


def _read_html(path: str) -> str:
    from bs4 import BeautifulSoup

    return BeautifulSoup(Path(path).read_text(errors="ignore"), "html.parser").get_text(" ", strip=True)


def extract_document(path: str) -> list[str]:
    """Return text 'pages' for any supported note format (no OCR — speed)."""
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return extract_pages(path, ocr_threshold=0)
    if ext == ".docx":
        return [_read_docx(path)]
    if ext in {".txt", ".md"}:
        return [Path(path).read_text(errors="ignore")]
    if ext in {".html", ".htm"}:
        return [_read_html(path)]
    return []


# --------------------------------------------------------------------------- #
# Chunking                                                                     #
# --------------------------------------------------------------------------- #
def _split_paragraphs(text: str, max_chars: int = 1200) -> list[str]:
    pieces: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        if len(block) <= max_chars:
            pieces.append(block)
        else:
            pieces.extend(line.strip() for line in block.split("\n") if line.strip())

    out: list[str] = []
    buf = ""
    for p in pieces:
        cand = f"{buf} {p}".strip() if buf else p
        if len(cand) <= max_chars:
            buf = cand
        else:
            if buf:
                out.append(buf)
            buf = p
    if buf:
        out.append(buf)
    return out


def chunk_pages(pages: list[str], case_no: str, source: Source = "judgment") -> list[Chunk]:
    chunks: list[Chunk] = []
    for pno, text in enumerate(pages, start=1):
        for i, para in enumerate(_split_paragraphs(text), start=1):
            chunks.append(Chunk(text=para, case_no=case_no, page=pno, para=str(i), source=source))
    return chunks


def case_no_from_filename(name: str) -> str:
    return Path(name).stem.replace("_", " ").upper()


# --------------------------------------------------------------------------- #
# Personal repository                                                          #
# --------------------------------------------------------------------------- #
def _clean_subject(name: str) -> str:
    return re.sub(r"^\d+\s*-\s*", "", name).strip()


def load_personal_repo(directory: str, limit: int | None = None) -> list[Chunk]:
    """Walk the notes folder; tag chunks with Subject / Category from the layout."""
    root = Path(directory)
    files = [
        p for p in sorted(root.rglob("*"))
        if p.is_file() and p.suffix.lower() in NOTE_EXTS
        and not p.name.startswith("~$") and not p.name.startswith(".")
    ]
    if limit:
        files = files[:limit]

    chunks: list[Chunk] = []
    for p in files:
        parts = p.relative_to(root).parts
        subject = _clean_subject(parts[0]) if parts else "General"
        category = parts[1] if len(parts) > 2 else "General"
        label = f"{subject} / {category} / {p.name}"
        try:
            pages = extract_document(str(p))
        except Exception:
            continue  # unreadable file — skip rather than fail the batch
        meta = {"subject": subject, "category": category, "filename": p.name}
        for c in chunk_pages(pages, case_no=label, source="personal_repo"):
            c.metadata.update(meta)
            chunks.append(c)
    return chunks


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Extract + chunk a judgment PDF.")
    ap.add_argument("pdf")
    ap.add_argument("--out", type=Path, default=None, help="write per-page extracted text here")
    ap.add_argument("--show", type=int, default=3, help="number of sample chunks to print")
    args = ap.parse_args(argv)

    case_no = case_no_from_filename(args.pdf)
    pages = extract_pages(args.pdf)
    chunks = chunk_pages(pages, case_no)
    print(f"{Path(args.pdf).name}: {len(pages)} pages, {len(chunks)} chunks, case_no={case_no!r}")
    for c in chunks[: args.show]:
        print(f"\n  {c.anchor()}\n   {c.text[:220].strip().replace(chr(10), ' ')}…")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        body = "\n".join(f"\n===== Page {pno} =====\n{text}" for pno, text in enumerate(pages, 1))
        args.out.write_text(body)
        print(f"\nExtracted text -> {args.out}")


if __name__ == "__main__":
    main()
