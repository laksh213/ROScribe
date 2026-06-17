# ROScribe — System Overview, Architecture & Roadmap

*Local-first, citation-grounded legal research over the Supreme Court of Sri Lanka.*

> Not legal advice. ROScribe structures, extracts and flags — a qualified lawyer
> must verify every citation. The source PDF is always shown next to any AI output.

---

## 1. What it is (and the problem it solves)

Sri Lankan Supreme Court judgments live as ~3,800 unstructured PDFs on a public
website. Finding the right precedent, understanding a case quickly, and checking
it against what you learned in law school is slow and manual.

**ROScribe** turns that pile of PDFs into a structured, searchable knowledge base
that runs entirely on your machine. It scrapes the judgments, extracts and indexes
them, lets you search by **meaning, keyword, judge, or legal area**, generates an
AI **breakdown** of each case, and cross-references everything against your own
law-school notes — so confidential data never leaves your computer.

Core question it answers: *"Can we use Case X as a precedent here?"*

---

## 2. How it works — the pipeline

```
   supremecourt.lk
        │  (1) SCRAPE          requests + BeautifulSoup
        ▼
   PDFs + manifest.json
        │  (2) INGEST          PyMuPDF text  ·  Tesseract OCR (eng+sin+tam)
        ▼                      → page/paragraph-anchored chunks
   chunks + metadata
        │  (3) STORE           SQLite (metadata + FTS5)  ·  ChromaDB (vectors)
        ▼
   index (~135k chunks)
        │  (4) RETRIEVE        semantic (bge-m3) · keyword (FTS5) · facets
        ▼
   relevant cases / text
        │  (5) ANALYZE         local LLM + schema → CaseAnalysis (cached)
        ▼
   (6) SERVE                   NiceGUI 3-pane workspace (auth + public demo)
```

### (1) Scrape — `src/scrape.py`
Two public sources merged by filename: the **archive table** (`/judgements/`,
server-rendered, ~2,580 rows with rich metadata — date, case no, parties, judge,
keywords, legislation, PDF URL) and the **directory index**
(`/wp-content/uploads/judgements/`, ~3,790 PDFs — the completeness spine). Merged
to ~3,859, downloads PDFs, writes `data/manifest.json` as an audit trail.
Resumable and rate-limited.

### (2) Ingest — `src/ingest.py`
**PyMuPDF** extracts the text layer fast; **Tesseract OCR** (`eng+sin+tam`) is the
fallback for scanned pages. Text is split into **page + paragraph-anchored
`Chunk`s** so every citation is verifiable as `[Case No | Page:Para]`.
`extract_bench()` parses the full **panel of judges** from the judgment's
"Before:" section (the scrape only records the authoring judge). The same module
ingests your **personal notes** (PDF/docx/txt/md/html), tagged by Subject/Category.

### (3) Store — `src/store.py`, `src/index.py`
- **SQLite** (`data/roscribe.db`): structured metadata (`judgements`), the
  breakdown cache (`analyses`), index state, a **FTS5 full-text** index
  (`chunks_fts`), plus user `bookmarks`/`annotations`.
- **ChromaDB** (`data/chroma`): **vector embeddings** for semantic search.
- Indexing is **resumable + idempotent** (re-runs skip done work). ~135k chunks
  total (judgments + notes).

### (4) Retrieve — `src/retrieve.py` + `src/store.py`
Three complementary modes:
- **Semantic** — `BAAI/bge-m3` multilingual embeddings → nearest chunks (optional
  `bge-reranker-v2-m3` re-rank).
- **Keyword** — SQLite **FTS5** for exact phrases, judge names, case numbers.
- **Faceted** — By Justice, By **legal area** (a curated 26-area taxonomy mapped
  to legal keywords + case-number prefixes), and by Year.

### (5) Analyze — `src/analyze.py` + `prompts/system_prompt.md`
A **pluggable LLM** (`LLM_PROVIDER`: `llamacpp` local-default, `ollama`, `openai`,
`anthropic`) reads the full judgment and returns a **validated `CaseAnalysis`**
(Pydantic, `src/schema.py`): topics, factual matrix, legal issues, evidence,
**precedent index** (Applied/Distinguished/Overruled/Followed), legislation,
deciding factors, **ratio decidendi**, final order, and **academic synthesis**
(vs your notes). Long judgments are context-fitted; output is JSON-grammar
constrained; results are generated **on demand and cached**.

### (6) Serve — `app/workspace.py` (NiceGUI)
A 3-pane "Scholar's Archive" workspace: **PDF** (left) · **Breakdown** (center) ·
**Library** (right). Closed-user-base **login**, public read-only **`/demo`**,
bookmarks, annotations, and clickable topic chips that jump to related cases.

---

## 3. Technologies used

| Layer | Tool | Why |
|---|---|---|
| Scraper | `requests` + `BeautifulSoup` | the source is server-rendered HTML |
| PDF / OCR | `PyMuPDF` + `Tesseract` (`eng+sin+tam`) | fast text + Sinhala/Tamil scans |
| Embeddings | `BAAI/bge-m3` | multilingual, local, strong retrieval |
| Reranker | `bge-reranker-v2-m3` | precision boost (optional) |
| Vector DB | **ChromaDB** | embedded, zero-config, local file |
| Metadata + FTS | **SQLite** (+ FTS5) | stdlib, no server, full-text keyword |
| Analysis LLM | **llama-cpp** (llama3.2:3b) · pluggable to Claude/OpenAI/Ollama | private, on-device by default |
| Schema | **Pydantic v2** | validated, typed structured output |
| UI | **NiceGUI** (FastAPI + Vue/Quasar) | Python, real PDF embed, reactive |
| Sharing | **Tailscale Funnel** | free public HTTPS URL, on/off switch |

**Design principles:** local-first & private · citation-grounded · *reliable
scraped metadata + AI analysis layered separately* · human-in-the-loop ·
hallucination-resistance (source-fidelity prompt + a re-runnable verifier).

---

## 4. Current features
Bulk resumable scraping with audit trail · OCR (EN/Sinhala/Tamil) · full corpus
indexed on bge-m3 (~135k chunks) · semantic + keyword + faceted search · clickable
topic → related cases · full-bench extraction · on-demand cached AI breakdowns ·
notes cross-reference · auth + public demo · bookmarks & annotations · on/off
switch (`scripts/roscribe.sh`) · public Tailscale URL · accuracy verifier
(`scripts/verify_breakdowns.py`).

---

## 5. Running it
```bash
./scripts/roscribe.sh start | stop | status | restart   # app + public URL
# local: http://localhost:8080   public: https://roscribesl.<tailnet>.ts.net (+ /demo)
ROSCRIBE_EMBEDDER=default .venv/bin/python scripts/verify_breakdowns.py   # QA audit
```
Hardware note: M3 Pro / 18 GB runs the 3B model + bge-m3 well (~40–60 s per
breakdown, then cached). qwen2.5:14b is too heavy to co-load here.

---

## 6. Roadmap — improvements, features, expansion, deployability

### A. Analysis quality & trust
1. **Precompute breakdowns** in the background → cases open instantly (only the
   first view is slow; it caches).
2. **Better analysis** — run a 14B/Claude model out-of-process or via API;
   extract **counsel names** and **explicit distinctions/holdings**.
3. **Verifier in CI** — gate on `verify_breakdowns.py`; add confidence flags.
4. **"Cited-by" / citation graph** — which *later* cases cite this one → "is this
   still good law?".
5. **Multi-case comparison** — 2–3 judgments side by side for precedent analysis.

### B. Search & navigation
6. **Auto-tag a legal area per case** (precompute) → exact area filter + a badge
   on every case.
7. **Jump-to-page citations** — click a precedent → open its PDF at the cited page.
8. **Combine filters** (Judge + Area + Year + Bookmarked) and **highlight search
   terms in the PDF**.
9. **Sinhala/Tamil search** surfaced in the UI (bge-m3 already indexes them).

### C. Content & data
10. **Keep the corpus fresh** — weekly incremental scrape + index of new judgments.
11. **Add corpora** — Court of Appeal, High Court, and a **statute browser** (Acts
    cited → full text), plus official headnotes/law reports.

### D. Personal research workspace
12. Finish **"My Research"** (saved cases/queries/highlights — bookmarks &
    annotations are started) and **export a breakdown/brief to PDF/Word**.
13. Wire the **precedent test** ("can we use Case X for *this* scenario?") into the
    UI, validated against your notes.
14. **Academic Cross-Reference popup** — select a term → your relevant notes.

### E. UX & polish
15. **Mobile single-pane tabbed** layout · dark mode · command palette · keyboard
    shortcuts · onboarding/empty states.

### F. Deployability (tiers)
16. **Now:** local + Tailscale Funnel for a closed group (the current setup).
17. **Stable branded URL:** Cloudflare *named* tunnel on a cheap domain
    (`roscribesl.yourdomain.com`).
18. **Multi-user:** real auth (Firebase/Supabase) + per-user data; or the
    **hybrid** model (publicly-hosted frontend + on-device GPU backend via tunnel,
    gated by a token — keeps notes + inference private).
19. **Packaging & reliability:** Docker for the non-GPU parts; a launchd service
    for auto-start/restart; backups of `data/`; rotate credentials; rate-limiting
    + audit logging.
20. **Cloud option:** move embeddings/LLM to a rented GPU for speed (judgments are
    public; keep private notes local) — fastest, but costs and trades some privacy.

### G. Moonshots
21. **Fine-tune** a small model on SL legal text + your notes (Unsloth/Axolotl) for
    sharper, domain-specific breakdowns.
22. **Cross-jurisdiction** expansion (other South Asian apex courts).
23. **Citation-network analytics**, a public **API**, and a native **mobile app**.

---

*Built iteratively with Claude Code. Architecture is intentionally modular —
each pipeline stage (`scrape → ingest → store → retrieve → analyze → serve`) is a
separate module you can improve or swap independently.*
