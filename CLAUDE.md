# ROScribe — Supreme Court of Sri Lanka Legal Research Platform

Citation-grounded RAG that scrapes, breaks down, and indexes Sri Lankan Supreme
Court judgements, cross-referenced against a personal legal repository
(law-school notes). Goal: verifiable, hallucination-resistant legal intelligence
to answer questions like *"can we use Case X as a precedent?"*.

> Auto-loaded into every Claude Code session here — the equivalent of "Project
> Instructions". The extraction prompt lives in `prompts/system_prompt.md`.

## Role
You are a senior legal-AI engineer. Build and operate the pipeline below; when
analysing judgements, follow the Operational Guidelines strictly.

## Stack (easy to implement · open source · Claude as the brain)
- **Scraper:** requests + BeautifulSoup (`src/scrape.py`) — implemented & tested.
- **PDF text / OCR:** PyMuPDF (fitz) + Tesseract (`eng+sin+tam`) fallback —
  open source; handles scanned + Sinhala/Tamil judgements.
- **Embeddings / rerank:** `BAAI/bge-m3` + `BAAI/bge-reranker-v2-m3`
  (multilingual, local, open source).
- **Storage (zero-config, local files — no server):** SQLite for structured
  metadata, ChromaDB for vectors.
- **Analysis:** pluggable LLM via `LLM_PROVIDER` — **Ollama (local, default)** for a
  fully on-device/private pipeline, or Anthropic / OpenAI. Isolated in `src/analyze.py`.
- **UI:** Streamlit.

Local-first: with Ollama + local embeddings, judgements AND personal notes never
leave the machine — the right default for confidential legal data.

## Pipeline (phases)
1. **Scrape** (`src/scrape.py`) — crawl the two SC sources, merge by filename,
   download PDFs + write `data/manifest.json` (metadata + audit trail). **DONE.**
2. **Ingest** (`src/ingest.py`) — PyMuPDF text, Tesseract OCR fallback →
   page-anchored `Chunk`s.
3. **Store** (`src/store.py`) — SQLite metadata + ChromaDB embeddings.
4. **Retrieve** (`src/retrieve.py`) — Chroma recall → BGE rerank; judgments
   first, then notes.
5. **Analyze** (`src/analyze.py`) — Claude + `prompts/system_prompt.md` →
   validated `CaseAnalysis`.

## Data sources (verified)
- Archive table `https://supremecourt.lk/judgements/` — ~2,580 rows, fully
  server-rendered, rich metadata (date, case no, parties, judge, keywords,
  legislation, pdf url). One GET retrieves all rows.
- Directory index `https://supremecourt.lk/wp-content/uploads/judgements/` —
  ~3,790 PDFs; the completeness spine for older files.
- Merged total: ~3,859 judgements.

## Output schema (the breakdown)
`src/schema.py :: CaseAnalysis`: `topics_discussed`, `factual_matrix` (facts),
`legal_issues`, `evidence_weighing` (evidence), `precedent_index` (case law
cited; Applied / Distinguished / Overruled / Followed), `legislation_cited`,
`deciding_factors`, `ratio_decidendi`, `final_order` (final judgement),
`academic_synthesis` (analysis vs personal repository).

## Operational Guidelines (when analysing judgements)
- **Source fidelity:** never guess. Missing detail → output exactly
  `Information not available in source text.`
- **Citation enforcement:** every claim cites `[Case No | Page:Para]`.
- **Precedent test** ("Can we use Case X?"): (1) retrieve facts + ratio of X,
  (2) map to the user's scenario, (3) validate against personal notes (laches,
  statutory conflicts, unexplained laches).
- **Languages:** English, Sinhala, Tamil; preserve original legal terms.
- **Conflicts:** flag where the court diverges from the personal repository.
- **Human-in-the-loop:** structure and flag; a lawyer verifies every citation.
  Always show the source PDF next to any AI summary. RAG reduces — it does not
  eliminate — error.

## Personal repository
The user's law-school notes live in a folder of `NN - Subject / Category / file`
(PDF, docx, txt, md, html), e.g. `01 - Civil Procedure 1 / Notes / x.pdf`.
`ingest.load_personal_repo` walks it, tagging each chunk with **subject** and
**category** (derived from the folder layout) and `source="personal_repo"`, then
stores it in the same Chroma collection alongside judgements. Index with:
`python -m src.index --notes "<PERSONAL_REPO_DIR>"`. Anchors read
`[Subject / Category / file | page:para]`.

## Status
Phases 1–4 implemented and verified on real data; Phase 5 wired (needs API key).
- **Scrape** (`src/scrape.py`): 3,859 judgements discovered; 15 downloaded as the demo corpus.
- **Ingest** (`src/ingest.py`): PyMuPDF text + Tesseract OCR fallback; page/para anchors.
- **Index** (`src/index.py` + `src/store.py`): 15 judgements → ~560 chunks in SQLite + Chroma.
- **Retrieve** (`src/retrieve.py`): semantic search verified; BGE rerank optional.
- **Analyze** (`src/analyze.py`): Claude breakdown + `precedent_test`; set `ANTHROPIC_API_KEY` to enable.
- **UI** (`app/streamlit_app.py`): search + breakdown tabs.

Embedding note: until `pip install -r requirements.txt` pulls sentence-transformers,
the index uses Chroma's default (English) embedder. Re-run `python -m src.index`
afterwards to switch to multilingual `bge-m3` (the collection name encodes the
embedder, so the two never clash).

## Conventions
Python 3.11+, Pydantic v2, type hints. Use the project `.venv`. Secrets in `.env`
(see `.env.example`); never commit `data/` contents or keys.
