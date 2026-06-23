# ROScribe
## AI-Powered Legal Intelligence for the Judiciary of Sri Lanka

**Confidential Briefing Document**

---

## The Problem

Sri Lanka's judiciary sits on decades of institutional knowledge locked inside
thousands of PDF judgements — many scanned, some in Sinhala or Tamil, most
searchable only by filename. Today, when a judge, registrar, or legal
researcher needs to answer a question as fundamental as *"Has the Supreme Court
addressed this issue before, and how?"*, the process looks like this:

1. **Manual keyword search** through filenames or memory.
2. **Read hundreds of pages** to extract the ratio decidendi.
3. **Cross-reference cited cases** by hand to determine whether precedent was
   applied, distinguished, or overruled.
4. **Repeat for every related judgement**, hoping nothing was missed.

This process is slow (days to weeks), error-prone, and entirely dependent on
the institutional memory of senior staff. When experienced registrars or
researchers retire, that knowledge leaves with them.

**The cost is real:** delayed case preparation, inconsistent application of
precedent, duplicated research effort across benches, and a growing backlog
that undermines public confidence in the speed and consistency of justice.

---

## The Solution: ROScribe

ROScribe is a **citation-grounded legal intelligence platform** purpose-built
for the Supreme Court of Sri Lanka. It ingests every publicly available Supreme
Court judgement, structures the content into a searchable knowledge base, and
delivers AI-powered analysis that is **always traceable to a specific page and
paragraph** in the source document.

Unlike generic AI tools, ROScribe is designed with a single, non-negotiable
principle: **every claim must cite its source**. There are no hallucinations
presented as fact — if the system cannot ground a statement in the actual
judgement text, it says so explicitly.

### What It Does

| Capability | Description |
|---|---|
| **Judgement Ingestion** | Automatically scrapes, downloads, and indexes all ~3,860 Supreme Court judgements from supremecourt.lk — including scanned PDFs via OCR in English, Sinhala, and Tamil. |
| **Structured Case Breakdown** | For any judgement, produces a structured analysis: facts, legal issues, evidence weighed, precedent cited (with treatment — Applied / Distinguished / Overruled / Followed), legislation relied upon, deciding factors, ratio decidendi, and final order. |
| **Semantic Search** | Natural-language queries across the entire corpus. Ask *"compensation in lieu of reinstatement"* and find every relevant judgement, ranked by relevance — not just keyword matches. |
| **Precedent Testing** | Ask *"Can we use SC Appeal 45/2019 as precedent for this scenario?"* and receive a grounded, step-by-step analysis: retrieve the candidate case's facts and ratio, compare against the new scenario, and flag any conflicts with established legal principles. |
| **Trilingual Support** | Full support for English, Sinhala, and Tamil using multilingual AI models — no judgement is inaccessible because of language. |
| **Citation Enforcement** | Every AI-generated claim includes a pin-cite in the format `[Case No | Page:Para]`, linking directly to the source material. |

---

## Why This Matters for the Judiciary

### 1. Accelerate Case Preparation
A structured breakdown that currently takes a researcher days can be generated
in minutes — with every citation verifiable against the source PDF displayed
alongside the analysis.

### 2. Ensure Consistency of Precedent
Semantic search surfaces *all* relevant prior decisions, not just the ones the
researcher remembers. The precedent index shows exactly how each cited case was
treated, making it straightforward to identify conflicting lines of authority.

### 3. Preserve Institutional Knowledge
When ROScribe indexes the corpus, the court's collective jurisprudence becomes
a structured, searchable asset — not dependent on any individual's memory.
New clerks and researchers can access decades of institutional knowledge on
day one.

### 4. Support Judicial Training
The structured breakdown format — topics, facts, legal issues, ratio, final
order — is a natural teaching tool for judicial education programmes.

### 5. Improve Public Transparency
A well-indexed, searchable judgement database strengthens the rule of law by
making the court's reasoning accessible and consistent.

---

## Architecture: Built for Judicial Confidence

### Data Sovereignty and Privacy

ROScribe is **local-first by design**. The default configuration runs entirely
on-premises:

- **No data leaves the judiciary's network.** All processing — OCR, indexing,
  search, and AI analysis — runs on local hardware.
- **No cloud dependency.** The default AI engine (Ollama) runs locally. No
  judgement text, query, or analysis is sent to any external server.
- **No vendor lock-in.** Every component is open source. The judiciary owns
  the installation, the data, and the pipeline.

For organisations comfortable with cloud AI, ROScribe also supports Anthropic
(Claude) or OpenAI as drop-in alternatives for higher-quality analysis, with
the switch requiring only one configuration change.

### Proven, Open-Source Stack

| Component | Technology | Why |
|---|---|---|
| Scraper | Python (requests + BeautifulSoup) | Reliably ingests all SC judgements from the existing website |
| PDF & OCR | PyMuPDF + Tesseract (eng + sin + tam) | Handles both digital and scanned documents in all three languages |
| Embeddings | BAAI/bge-m3 (multilingual) | State-of-the-art multilingual semantic understanding, runs locally |
| Re-ranking | BAAI/bge-reranker-v2-m3 | Ensures the most relevant results surface first |
| Metadata Store | SQLite | Zero-configuration, battle-tested, used by courts worldwide |
| Vector Store | ChromaDB | Fast semantic search over hundreds of thousands of document chunks |
| AI Analysis | Pluggable (Ollama / Claude / OpenAI) | Local default; cloud option for maximum quality |
| User Interface | Streamlit | Clean, web-based UI accessible from any browser on the court's network |

### Accuracy Safeguards

- **Human-in-the-loop:** ROScribe structures and flags — a qualified legal
  officer verifies. The source PDF is always displayed alongside any AI summary.
- **No hallucination by design:** The extraction prompt enforces that any field
  not grounded in the source text outputs `"Information not available in source
  text."` rather than fabricating an answer.
- **Conflict detection:** When the AI analysis diverges from established legal
  doctrine, the system explicitly flags the conflict for human review.

---

## Current Status: Working Prototype

ROScribe is not a concept — it is a working system tested on real Supreme Court
data:

| Milestone | Status |
|---|---|
| Scraper operational — 3,859 judgements discovered and catalogued | Complete |
| PDF ingestion with OCR fallback (English, Sinhala, Tamil) | Complete |
| Indexing pipeline — judgements chunked with page/paragraph anchors | Complete |
| Semantic search — verified on 15-judgement demo corpus (~560 chunks) | Complete |
| Structured case breakdown via AI — validated output schema | Complete |
| Precedent test — grounded, citation-backed analysis | Complete |
| Web-based user interface (search, breakdown, precedent tabs) | Complete |
| Personal repository integration (law notes, academic materials) | Complete |
| Full corpus ingestion (all 3,859 judgements) | Ready to deploy |

---

## Deployment Roadmap

### Phase 1: Pilot (Months 1-3)
- Deploy on a single workstation within the Supreme Court Registry.
- Index the full corpus of ~3,860 judgements.
- Train 2-3 research officers on the search and breakdown interface.
- Validate output quality against manually prepared case summaries.
- **Cost: Minimal** — runs on existing hardware; all software is open source.

### Phase 2: Registry Rollout (Months 4-6)
- Deploy on a local server accessible to all research staff via browser.
- Integrate with the court's internal network.
- Add user authentication and audit logging.
- Expand the personal repository with the court's internal research notes.
- Gather feedback and refine the analysis prompts.

### Phase 3: Expansion (Months 7-12)
- Extend to the Court of Appeal corpus.
- Add automated ingestion of newly published judgements.
- Develop a judicial benchbook feature — curated, structured summaries by
  legal topic.
- Evaluate cloud AI (Claude) for complex analyses requiring larger context
  windows.

### Phase 4: National Legal Intelligence (Year 2+)
- Integrate with other court tiers (High Court, District Courts).
- API access for the Attorney General's Department, Legal Aid Commission, and
  law faculties.
- Cross-jurisdictional analysis (e.g., Privy Council decisions, comparative
  Commonwealth jurisprudence).

---

## Investment and Sustainability

### Why Open Source Matters for the Judiciary

- **No licensing fees.** Every component of ROScribe is open source.
- **No recurring cloud costs** in the default (local) configuration.
- **No vendor dependency.** The judiciary can maintain, modify, and extend the
  system with local technical staff or any qualified contractor.
- **Auditability.** The full source code is available for inspection — critical
  for a system that supports judicial decision-making.

### What Is Needed

| Item | Estimate |
|---|---|
| Server hardware (if not using existing) | One capable workstation or server with GPU for local AI |
| Technical deployment and configuration | 1-2 weeks of engineering time |
| Training for research staff | 1-2 days |
| Ongoing maintenance | Part-time technical support; the system is designed to be low-maintenance |

The total cost of ownership is a fraction of any commercial legal research
platform, with the critical advantage of **complete data sovereignty**.

---

## Comparable Initiatives

Judiciaries worldwide are adopting AI-assisted legal research:

- **Singapore** — the Supreme Court uses AI tools for judgement summarisation
  and search.
- **India** — SUPACE (Supreme Court Portal for Assistance in Court Efficiency)
  uses AI to process case files and identify relevant precedent.
- **United Kingdom** — the Courts and Tribunals Judiciary invested in
  AI-powered case management and research tools.
- **Canada** — the Supreme Court has explored AI-assisted legal research to
  reduce case preparation time.

ROScribe positions Sri Lanka's judiciary alongside these global peers, with the
added advantages of trilingual support and complete on-premises privacy.

---

## Summary

ROScribe transforms the Supreme Court's judgement archive from a collection of
static PDFs into a **living, searchable, structured knowledge base** — one
where any researcher can find relevant precedent in seconds, understand how it
was treated, and verify every claim against the source document.

It does this **without sending a single document outside the judiciary's
network**, using **entirely open-source technology**, at a **fraction of the
cost** of commercial alternatives.

The prototype is built, tested, and ready to scale.

---

*ROScribe — Verifiable legal intelligence for the courts of Sri Lanka.*

**Contact:** smslakshman@gmail.com
