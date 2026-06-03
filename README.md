# ROScribe

Scrapes, breaks down, and indexes **Supreme Court of Sri Lanka** judgements into a searchable repository — cross-referenced against personal legal notes — to support legal research questions such as *“can we use Case X as a precedent?”*

> **Not legal advice.** This system structures, extracts, and flags legal information. All citations and AI-generated outputs must be independently verified by a qualified legal professional. The source PDF is always shown alongside any AI-generated summary.

---

## Overview

ROScribe is a legal research pipeline designed to transform unstructured Supreme Court of Sri Lanka judgements into a structured, searchable knowledge base. It combines document scraping, OCR processing, embeddings-based retrieval, and LLM-based legal analysis.

The system is designed to function fully locally with minimal external dependencies.

---

## Stack (Open Source · Local-first · LLM-powered)

| Layer           | Tool                                     |
| --------------- | ---------------------------------------- |
| Scraper         | `requests`, `BeautifulSoup`              |
| PDF Processing  | `PyMuPDF`, `Tesseract OCR (eng+sin+tam)` |
| Embeddings      | `bge-m3`                                 |
| Reranker        | `bge-reranker-v2-m3`                     |
| Vector Database | ChromaDB (local file-based)              |
| Metadata Store  | SQLite (stdlib, no server)               |
| Analysis Engine | Claude (Anthropic API)                   |
| UI              | Streamlit                                |

---

## Project Structure

```
src/scrape.py     Phase 1 — Scraper (implemented)
src/ingest.py     Phase 2 — PDF extraction + OCR chunking
src/store.py      Phase 3 — SQLite + ChromaDB indexing
src/retrieve.py   Phase 4 — Vector search + reranking
src/analyze.py    Phase 5 — Claude-based legal analysis
src/schema.py     Structured analysis schema (Pydantic)

app/              Streamlit UI
prompts/          Prompt templates for extraction
data/
  sc_judgements/   Downloaded Supreme Court PDFs
  manifest.json    Metadata + audit trail
  personal_repo/   User legal notes
CLAUDE.md         Project instructions for Claude Code
```

---

## Features

* Bulk scraping of Supreme Court of Sri Lanka judgements
* Resumable download system with audit trail
* OCR support for Sinhala and Tamil scanned PDFs
* Structured metadata extraction (case name, judges, citations, legislation)
* Vector-based semantic search over judgements and personal notes
* Reranked retrieval for improved legal relevance
* LLM-powered case breakdown and analysis
* Cross-referencing between case law and personal research notes

---

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# Add your ANTHROPIC_API_KEY
```

### OCR Setup (Required for scanned PDFs)

```bash
brew install tesseract tesseract-lang
```

Includes Sinhala and Tamil language support.

---

## Data Storage

No external database servers are required.

* SQLite stores structured metadata
* ChromaDB stores embeddings locally
* All files persist under `/data`

---

## Scraping Judgements (Phase 1)

```bash
python -m src.scrape --dry-run
python -m src.scrape --metadata-only
python -m src.scrape --limit 20
python -m src.scrape --year 2024
python -m src.scrape
```

Output:

* PDFs → `data/sc_judgements/`
* Metadata → `data/manifest.json`

Supports resumable downloads and skips existing files automatically.

---

## Running the System

### Web UI

```bash
streamlit run app/streamlit_app.py
```

### Tests

```bash
pytest -q
```

---

## Pipeline Architecture

1. **Scrape** — Collect Supreme Court judgements
2. **Ingest** — Extract text via PyMuPDF + OCR fallback
3. **Store** — Chunk and store embeddings + metadata
4. **Retrieve** — Semantic search + reranking
5. **Analyze** — Claude generates structured legal breakdown

---

## Current Status

* Phase 1 (Scraper): Implemented and tested (~3,800 judgements discovered)
* Phase 2–5: Designed and scaffolded, ready for implementation
* System is currently in active development (MVP stage)

---

## Roadmap

* Improve OCR accuracy for Sinhala/Tamil legal scans
* Add citation graph between cases
* Implement advanced legal reasoning prompts
* Expand cross-referencing with user personal notes
* Build exportable case briefs (PDF/Word)

---

## Notes

This system is designed for **legal research assistance only** and does not replace professional legal interpretation. All outputs must be verified against primary legal sources.
