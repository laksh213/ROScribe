"""Phase 2 — Text extraction & chunking (open source).

PyMuPDF (fitz) extracts the text layer fast. If a page has too little text (a
scanned image), fall back to Tesseract OCR with `eng+sin+tam` so Sinhala and
Tamil judgements work. Chunks keep page + paragraph anchors so citations
`[Case No | Page:Para]` stay verifiable.

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


@dataclass
class Chunk:
    text: str
    case_no: str
    page: int
    para: str | None = None
    source: Source = "judgment"
    metadata: dict = field(default_factory=dict)  # e.g. {"Category", "Subject"}

    def anchor(self) -> str:
        return f"[{self.case_no} | {self.page}:{self.para}]"


def _ocr_page(page: "fitz.Page", langs: str) -> str:
    """OCR a page image with Tesseract. Returns "" if OCR deps are missing."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""
    pix = page.get_pixmap(dpi=300)
    return pytesseract.image_to_string(Image.open(io.BytesIO(pix.tobytes("png"))), lang=langs)


def extract_pages(pdf_path: str, ocr_langs: str = "eng+sin+tam", ocr_threshold: int = 200) -> list[str]:
    """Per-page text via PyMuPDF; OCR pages whose text layer is below threshold."""
    pages: list[str] = []
    with fitz.open(pdf_path) as doc:
        for page in doc:
            text = page.get_text("text")
            if len(text.strip()) < ocr_threshold:
                text = _ocr_page(page, ocr_langs) or text
            pages.append(text)
    return pages


def _split_paragraphs(text: str, max_chars: int = 1200) -> list[str]:
    """Split on blank lines, hard-split oversized blocks, then re-pack to ~max_chars."""
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
    """Split per-page text into page/paragraph-anchored chunks."""
    chunks: list[Chunk] = []
    for pno, text in enumerate(pages, start=1):
        for i, para in enumerate(_split_paragraphs(text), start=1):
            chunks.append(Chunk(text=para, case_no=case_no, page=pno, para=str(i), source=source))
    return chunks


def case_no_from_filename(name: str) -> str:
    """Best-effort case number from a PDF filename (manifest metadata is preferred)."""
    return Path(name).stem.replace("_", " ").upper()


def load_personal_repo(directory: str) -> list[Chunk]:
    """Load tagged Markdown notes from data/personal_repo/ into chunks."""
    raise NotImplementedError("Phase 2: parse Markdown notes + metadata tags.")


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
