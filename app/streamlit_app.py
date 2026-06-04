"""ROScribe — Streamlit UI (draft).

Run:  streamlit run app/streamlit_app.py

Three tabs over the local index:
  • Search     — semantic search across judgements + your notes
  • Breakdown  — structured CaseAnalysis for one judgement (via the configured LLM)
  • Precedent  — "can we use Case X as a precedent?" for a scenario

Everything runs locally; the LLM is whatever LLM_PROVIDER points at.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# Make the project root importable when launched as `streamlit run app/streamlit_app.py`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st

from src import store
from src.config import settings
from src.retrieve import retrieve

st.set_page_config(page_title="ROScribe", page_icon="⚖️", layout="wide")

st.markdown(
    """
    <style>
      #MainMenu, footer, [data-testid="stToolbar"] {visibility: hidden;}
      .block-container {padding-top: 2.4rem; max-width: 1080px;}
      .src-badge {font-size:0.70rem; font-weight:700; padding:2px 8px;
                  border-radius:10px; color:#fff; letter-spacing:.02em;}
      .badge-jud {background:#2563eb;} .badge-note {background:#059669;}
      .anchor {font-family: ui-monospace, SFMono-Regular, monospace;
               font-size:0.80rem; color:#475569;}
    </style>
    """,
    unsafe_allow_html=True,
)


# ----------------------------- data helpers ------------------------------- #
@st.cache_resource(show_spinner=False)
def _collection():
    return store.get_collection()


@st.cache_data(show_spinner=False)
def corpus_stats() -> dict:
    col = _collection()
    try:
        j = len(col.get(where={"source": "judgment"}, include=[])["ids"])
        n = len(col.get(where={"source": "personal_repo"}, include=[])["ids"])
        total = col.count()
    except Exception:
        j = n = total = 0
    return {"judgements": j, "notes": n, "total": total}


@st.cache_data(show_spinner=False)
def list_cases() -> list[dict]:
    db = Path(settings.sqlite_path)
    if not db.exists():
        return []
    con = sqlite3.connect(str(db))
    rows = con.execute(
        "SELECT case_no, date, parties, local_path, pdf_url "
        "FROM judgements ORDER BY date DESC"
    ).fetchall()
    con.close()
    keys = ["case_no", "date", "parties", "local_path", "pdf_url"]
    return [dict(zip(keys, r)) for r in rows]


def _badge(source: str) -> str:
    if source == "personal_repo":
        return '<span class="src-badge badge-note">NOTE</span>'
    return '<span class="src-badge badge-jud">JUDGEMENT</span>'


def _render_breakdown(bd: dict) -> None:
    meta = bd.get("metadata", {})
    st.markdown(f"### {meta.get('case_no', '')}")
    c = st.columns(3)
    c[0].markdown(f"**Date**\n\n{meta.get('date', '—')}")
    c[1].markdown(f"**Judges**\n\n{', '.join(meta.get('judges', [])) or '—'}")
    c[2].markdown(f"**Court**\n\n{meta.get('court_division', '—')}")
    if bd.get("topics_discussed"):
        st.markdown("**Topics:** " + " · ".join(bd["topics_discussed"]))
    st.markdown("#### Facts")
    st.write(bd.get("factual_matrix"))
    if bd.get("deciding_factors"):
        st.markdown("#### Deciding factors")
        for d in bd["deciding_factors"]:
            st.markdown(f"- {d}")
    if bd.get("precedent_index"):
        st.markdown("#### Case law cited")
        for p in bd["precedent_index"]:
            st.markdown(f"- *{p.get('cited_case', '')}* — **{p.get('treatment', '')}**")
    if bd.get("legislation_cited"):
        st.markdown("**Legislation:** " + "; ".join(bd["legislation_cited"]))
    st.markdown("#### Final order")
    st.write(bd.get("final_order"))
    with st.expander("Full structured JSON"):
        st.json(bd)


cases = list_cases()
stats = corpus_stats()

# ------------------------------- header ----------------------------------- #
st.title("⚖️ ROScribe")
st.caption(
    "Supreme Court of Sri Lanka — legal research over judgements and your notes. "
    "Not legal advice; verify every citation against the source PDF."
)

# ------------------------------- sidebar ---------------------------------- #
with st.sidebar:
    st.subheader("Corpus")
    a, b = st.columns(2)
    a.metric("Judgements", stats["judgements"])
    b.metric("Note chunks", stats["notes"])
    st.caption(f"{stats['total']} total chunks indexed")
    st.divider()
    st.subheader("Engine")
    model = settings.anthropic_model if settings.llm_provider == "anthropic" else settings.llm_model
    st.write(f"**LLM** · `{settings.llm_provider}` / `{model}`")
    st.write(f"**Embeddings** · `{store.COLLECTION.replace('judgements_', '')}`")
    if not cases:
        st.warning("No index yet:\n```\npython -m src.scrape --limit 15\npython -m src.index\n```")

# -------------------------------- tabs ------------------------------------ #
tab_search, tab_breakdown, tab_precedent = st.tabs(
    ["🔎 Search", "📋 Case breakdown", "⚖️ Precedent test"]
)

with tab_search:
    q = st.text_input("Search across the corpus",
                      placeholder="e.g. compensation in lieu of reinstatement")
    left, right = st.columns([3, 1])
    scope = left.radio("Scope", ["All", "Judgements", "My notes"],
                       horizontal=True, label_visibility="collapsed")
    k = right.slider("Results", 3, 15, 6, label_visibility="collapsed")
    source = {"All": None, "Judgements": "judgment", "My notes": "personal_repo"}[scope]
    if q:
        hits = retrieve(q, k, source=source)
        if not hits:
            st.info("No results — try the other scope, or build the index.")
        for h in hits:
            m = h["meta"]
            with st.container(border=True):
                st.markdown(f"{_badge(m.get('source', ''))} &nbsp; "
                            f"<span class='anchor'>{m.get('anchor', '')}</span>",
                            unsafe_allow_html=True)
                st.write(h["text"])

with tab_breakdown:
    if not cases:
        st.info("Index some judgements first.")
    else:
        labels = [f"{c['case_no']} · {c['date']}" for c in cases]
        i = st.selectbox("Judgement", range(len(labels)), format_func=lambda i: labels[i])
        sel = cases[i]
        with st.container(border=True):
            st.markdown(f"**{sel['case_no']}**  ·  {sel['date']}")
            st.caption(sel["parties"][:240] + ("…" if len(sel["parties"]) > 240 else ""))
            if sel.get("pdf_url"):
                st.link_button("Open source PDF ↗", sel["pdf_url"])
        c1, c2 = st.columns(2)
        gen = c1.button("Generate / view breakdown", type="primary", use_container_width=True)
        regen = c2.button("Regenerate", use_container_width=True)
        if gen or regen:
            from src.analyze import analyze_case

            try:
                with st.spinner(f"Analysing with {settings.llm_provider}… (cached after first run)"):
                    st.session_state["bd"] = analyze_case(sel["case_no"], force=regen).model_dump()
            except Exception as e:
                st.session_state["bd"] = None
                st.error(str(e))
        if st.session_state.get("bd"):
            _render_breakdown(st.session_state["bd"])

with tab_precedent:
    st.write("Test whether a judgement supports your scenario.")
    if not cases:
        st.info("Index some judgements first.")
    else:
        labels = [c["case_no"] for c in cases]
        ci = st.selectbox("Candidate precedent", range(len(labels)),
                          format_func=lambda i: labels[i])
        scenario = st.text_area("Your scenario / facts", height=140,
                                placeholder="Describe the facts to test the precedent against…")
        if st.button("Run precedent test", type="primary", disabled=not scenario.strip()):
            from src.analyze import precedent_test

            try:
                with st.spinner("Reasoning…"):
                    st.session_state["pt"] = precedent_test(labels[ci], scenario)
            except Exception as e:
                st.session_state["pt"] = None
                st.error(str(e))
        if st.session_state.get("pt"):
            with st.container(border=True):
                st.markdown(st.session_state["pt"])
