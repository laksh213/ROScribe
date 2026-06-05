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
    try:
        pix = page.get_pixmap(dpi=300)
        return pytesseract.image_to_string(Image.open(io.BytesIO(pix.tobytes("png"))), lang=langs)
    except Exception:
        return ""  # tesseract binary missing or OCR failed — keep the text layer


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
# Bench (the coram / panel of judges)                                          #
# --------------------------------------------------------------------------- #
# The web scrape only records the *authoring* judge. The full panel that heard
# the appeal is printed in the judgment's front matter, introduced by a marker
# like "Before :", "BEFORE", "Coram", or "Present :", followed by 1–3 names that
# each end in a judicial suffix (J. / C.J. / J., PC / etc.). `extract_bench`
# parses that panel straight from the text so the UI can show every judge.

# Markers that introduce the panel. Matched only at the start of a line so a
# stray "before the court" mid-sentence never triggers extraction.
_BENCH_MARKER = re.compile(
    r"^[\s>*•\-]*"
    r"(?:BEFORE|CORAM|PRESENT|BENCH|QUORUM)"
    r"\s*[:\-–.]*\s*",
    re.IGNORECASE,
)

# A line clearly belonging to a *different* labelled section — stop collecting
# the panel once we hit one of these.
_BENCH_STOP = re.compile(
    r"^[\s>*•\-]*"
    r"(?:COUNSEL|ARGUED|DECIDED|DELIVERED|JUDG(?:E)?MENT|JUDGEMENT|ORDER|FOR\s+THE|"
    r"PETITIONER|RESPONDENT|APPELLANT|PLAINTIFF|DEFENDANT|ON\s+BEHALF|"
    r"WRITTEN\s+SUBMISSION|DATE\s+OF|S\.?C\.?\s|C\.?A\.?\s|IN\s+THE\s+MATTER)",
    re.IGNORECASE,
)

# A judicial suffix at the end of a candidate name: J. / J / C.J. / CJ /
# J., PC / PC, J. / ACJ / DCJ … (tolerant of spaces, optional trailing dot).
_JUDGE_SUFFIX = re.compile(
    r"(?:,?\s*(?:P\.?C\.?|Q\.?C\.?|PC|QC))?"      # optional silk: PC / QC
    r"\s*,?\s*"
    r"(?:C\.?\s*J\.?|A\.?\s*C\.?\s*J\.?|D\.?\s*C\.?\s*J\.?|J\.?)"  # CJ / ACJ / DCJ / J
    r"\s*$",
    re.IGNORECASE,
)

# Honorifics / titles to strip from the front of a name (keep the suffix).
_HONORIFIC_PREFIX = re.compile(
    r"^(?:the\s+)?"
    r"(?:hon(?:'?ble|ourable|orable)?\.?\s*)?"
    r"(?:(?:mr|mrs|ms|dr)\.?\s*)?"
    r"(?:justice\s+|judge\s+)?",
    re.IGNORECASE,
)


def _clean_judge(raw: str) -> str | None:
    """Normalise one candidate into 'Name, J.'-style, or None if it isn't a judge."""
    name = raw.strip(" \t\r\n.,;:·•*->–—")
    name = re.sub(r"\s+", " ", name).strip()
    if not name:
        return None
    # Drop a leading numbering like "1." or "(i)".
    name = re.sub(r"^\(?\s*[0-9ivx]+\s*[.)]\s*", "", name, flags=re.IGNORECASE)
    name = _HONORIFIC_PREFIX.sub("", name).strip(" .,")
    if not _JUDGE_SUFFIX.search(name):
        return None
    # Reject lines that are obviously not a person (too long / sentence-like).
    if len(name) > 70 or name.count(" ") > 8:
        return None
    # Require at least one capitalised alphabetic name token before the suffix.
    head = _JUDGE_SUFFIX.sub("", name).strip(" ,.")
    if not re.search(r"[A-Za-z]{2,}", head):
        return None
    return name


def _split_candidates(block: str) -> list[str]:
    """Break a bench block into individual name candidates.

    Names can be newline-separated, joined by 'and' / '&', or comma-separated.
    We split on newlines and 'and'/'&' always; commas only when the following
    fragment still looks like it carries a judicial suffix, so 'Wijeratne, J.'
    (a name + its own suffix) is NOT split apart.
    """
    parts: list[str] = []
    for line in re.split(r"[\n\r]+|\s+&\s+|\s+\band\b\s+", block, flags=re.IGNORECASE):
        line = line.strip()
        if not line:
            continue
        # A line may pack several judges, e.g. "A, J., B, J." (comma-separated)
        # or "A, J.  B, J." (space-separated). Insert a split point right after
        # each judicial suffix that is followed by another (capitalised) name,
        # then split on those points. Matching '...J.' / '...J' / '...C.J.'.
        marked = re.sub(
            r"((?:C\.?\s*J|A\.?\s*C\.?\s*J|D\.?\s*C\.?\s*J|J)\.?)"  # a suffix
            r"\s*[,;]?\s+"                                          # gap to next
            r"(?=(?:(?:the\s+)?(?:hon(?:'?ble|ourable|orable)?\.?\s*)?"
            r"(?:justice\s+)?)?[A-Z])",                            # next name starts
            lambda mm: mm.group(1) + "\x00",
            line,
            flags=re.IGNORECASE,
        )
        for seg in marked.split("\x00"):
            seg = seg.strip(" \t,;")
            if seg:
                parts.append(seg)
    return parts


def extract_bench(pages_or_path) -> list[str]:
    """Parse the full panel of judges (the coram) from a judgment.

    Accepts a PDF path (str / Path), a single text string, or a list of page
    strings (as returned by `extract_pages`). Returns the judges in the order
    printed, each normalised like ``"Mahinda Samayawardhena, J."``. Returns
    ``[]`` when no panel can be confidently identified — callers should then
    fall back to the scrape metadata.
    """
    # --- normalise input to a single search text (front matter only) ---------
    if isinstance(pages_or_path, (list, tuple)):
        pages = list(pages_or_path)
    elif isinstance(pages_or_path, Path) or (
        isinstance(pages_or_path, str)
        and pages_or_path.lower().endswith(".pdf")
        and Path(pages_or_path).exists()
    ):
        try:
            pages = extract_pages(str(pages_or_path))
        except Exception:
            return []
    else:
        pages = [str(pages_or_path)]

    # The coram is in the front matter; search the first two pages only.
    text = "\n".join(str(p) for p in pages[:2])
    if not text.strip():
        return []

    lines = text.splitlines()
    judges: list[str] = []

    for idx, line in enumerate(lines):
        m = _BENCH_MARKER.match(line)
        if not m:
            continue

        # Collect the marker's own remainder plus the lines beneath it, until a
        # clearly different section or a run of non-judge lines ends the panel.
        block_lines: list[str] = []
        remainder = line[m.end():].strip()
        if remainder:
            block_lines.append(remainder)

        misses = 0
        for nxt in lines[idx + 1:]:
            if _BENCH_STOP.match(nxt):
                break
            stripped = nxt.strip()
            if not stripped:
                # A blank line ends the block only once we already have names.
                if block_lines and any(_clean_judge(c) for c in _split_candidates("\n".join(block_lines))):
                    break
                continue
            block_lines.append(stripped)
            # Stop early if we have collected a few non-judge lines in a row.
            if _clean_judge(stripped) is None:
                misses += 1
                if misses >= 2:
                    break
            else:
                misses = 0
            # A panel is at most three judges; once we have them, stop.
            got = [j for c in _split_candidates("\n".join(block_lines)) if (j := _clean_judge(c))]
            if len(got) >= 3:
                break

        for cand in _split_candidates("\n".join(block_lines)):
            j = _clean_judge(cand)
            if j and j not in judges:
                judges.append(j)

        if judges:
            break  # first valid panel wins; ignore later "before" mentions

    return judges


# --------------------------------------------------------------------------- #
# Personal repository                                                          #
# --------------------------------------------------------------------------- #
def _clean_subject(name: str) -> str:
    return re.sub(r"^\d+\s*-\s*", "", name).strip()


def list_note_files(directory: str) -> list[tuple[Path, str, str]]:
    """Return (path, subject, category) for every supported note file."""
    root = Path(directory)
    out: list[tuple[Path, str, str]] = []
    for p in sorted(root.rglob("*")):
        if (
            p.is_file()
            and p.suffix.lower() in NOTE_EXTS
            and not p.name.startswith("~$")
            and not p.name.startswith(".")
        ):
            parts = p.relative_to(root).parts
            subject = _clean_subject(parts[0]) if parts else "General"
            category = parts[1] if len(parts) > 2 else "General"
            out.append((p, subject, category))
    return out


def chunks_for_note(path: Path, subject: str, category: str) -> list[Chunk]:
    """Extract + chunk one note file, tagged with subject / category."""
    label = f"{subject} / {category} / {path.name}"
    meta = {"subject": subject, "category": category, "filename": path.name}
    chunks = chunk_pages(extract_document(str(path)), case_no=label, source="personal_repo")
    for c in chunks:
        c.metadata.update(meta)
    return chunks


def load_personal_repo(directory: str, limit: int | None = None) -> list[Chunk]:
    """Walk the notes folder; tag chunks with Subject / Category from the layout."""
    files = list_note_files(directory)
    if limit:
        files = files[:limit]
    chunks: list[Chunk] = []
    for p, subject, category in files:
        try:
            chunks.extend(chunks_for_note(p, subject, category))
        except Exception:
            continue  # unreadable file — skip rather than fail the batch
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
