# ROScribe

Scrapes, breaks down, and indexes **Supreme Court of Sri Lanka** judgements into
a searchable repository — cross-referenced against your personal legal notes — to
answer research questions like *"can we use Case X as a precedent?"*

> **Not legal advice.** The system structures and flags; a qualified lawyer must
> verify every citation. The source PDF is always shown next to any AI summary.

## Stack (open source · zero-config · Claude as the brain)
| Layer | Tool |
|---|---|
| Scraper | requests + BeautifulSoup |
| PDF text / OCR | PyMuPDF + Tesseract (`eng+sin+tam`) |
| Embeddings / rerank | `bge-m3` + `bge-reranker-v2-m3` (multilingual) |
| Vector DB | ChromaDB (local file, no server) |
| Metadata DB | SQLite (stdlib, no server) |
| Analysis | Claude (`claude-opus-4-8`) |
| UI | Streamlit |

## Setup
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add ANTHROPIC_API_KEY

# Tesseract OCR (only needed for scanned / Sinhala / Tamil PDFs)
brew install tesseract tesseract-lang   # macOS; bundles sin + tam
```
No database server to install — SQLite and ChromaDB are local files under `data/`.

## Scrape judgements (Phase 1 — working)
```bash
python -m src.scrape --dry-run          # preview, no downloads
python -m src.scrape --metadata-only    # build data/manifest.json only
python -m src.scrape --limit 20         # download first 20 PDFs
python -m src.scrape --year 2024        # one year only
python -m src.scrape                     # everything (~3,800 PDFs — be patient)
```
Output: PDFs in `data/sc_judgements/`, metadata + audit trail in
`data/manifest.json` (case no, date, parties, judges, keywords, legislation,
source URL, download time). Resumable — re-runs skip files already downloaded.

## Run
```bash
streamlit run app/streamlit_app.py   # UI
pytest -q                            # tests
```

## Layout
```
src/scrape.py    Phase 1 — scraper (done)
src/ingest.py    Phase 2 — PyMuPDF + Tesseract OCR -> chunks
src/store.py     Phase 3 — SQLite metadata + ChromaDB vectors
src/retrieve.py  Phase 4 — Chroma recall -> BGE rerank
src/analyze.py   Phase 5 — Claude -> CaseAnalysis breakdown
src/schema.py    the breakdown contract (Pydantic)
app/             Streamlit UI
prompts/         extraction system prompt
data/            sc_judgements/ (PDFs) + personal_repo/ (notes) + manifest.json
CLAUDE.md        project instructions (auto-loaded by Claude Code)
```

## Status
Phase 1 scraper is implemented and tested (3,859 judgements discovered). Pipeline
modules 2–5 are documented stubs — implement Phase 2 (ingestion) next, validating
text + OCR on a handful of downloaded PDFs.
