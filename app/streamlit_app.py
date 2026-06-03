"""ROScribe — Streamlit prototype UI.

Run:  streamlit run app/streamlit_app.py

- Sidebar: browse indexed judgements; generate a Claude breakdown of one.
- Search tab: semantic search across all indexed judgements (Phase 3–4).
- Breakdown tab: the structured CaseAnalysis for the selected case (Phase 5).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import streamlit as st

from src.config import settings
from src.retrieve import retrieve

st.set_page_config(page_title="ROScribe — SC Legal Research", layout="wide")
st.title("ROScribe · Supreme Court of Sri Lanka — Legal Research")
st.caption("Citation-grounded RAG. Not legal advice — verify every citation against the source PDF.")


@st.cache_data(show_spinner=False)
def list_cases() -> list[tuple]:
    db = Path(settings.sqlite_path)
    if not db.exists():
        return []
    con = sqlite3.connect(str(db))
    rows = con.execute(
        "SELECT case_no, date, parties, local_path, n_chunks "
        "FROM judgements ORDER BY date DESC"
    ).fetchall()
    con.close()
    return rows


cases = list_cases()

with st.sidebar:
    st.header("Indexed judgements")
    if not cases:
        st.info("No index found. Build one:\n\n```\npython -m src.scrape --limit 15\npython -m src.index\n```")
        selected = None
    else:
        st.write(f"**{len(cases)}** cases indexed")
        labels = [f"{c[0]}  ·  {c[1]}" for c in cases]
        i = st.selectbox("Select a case", range(len(labels)), format_func=lambda i: labels[i])
        selected = cases[i]
        st.caption(selected[2][:200] + ("…" if len(selected[2]) > 200 else ""))
        if st.button("⚖️  Generate breakdown", use_container_width=True):
            from src.analyze import analyze_pdf

            try:
                with st.spinner("Analysing with Claude…"):
                    st.session_state["breakdown"] = analyze_pdf(selected[3]).model_dump()
            except Exception as e:  # missing key, parse error, etc.
                st.session_state["breakdown"] = None
                st.warning(str(e))

search_tab, breakdown_tab = st.tabs(["🔎 Semantic search", "📋 Case breakdown"])

with search_tab:
    q = st.text_input("Ask across all indexed judgements",
                      placeholder="e.g. compensation in lieu of reinstatement")
    k = st.slider("Results", 3, 15, 5)
    if q:
        for h in retrieve(q, k):
            m = h["meta"]
            with st.expander(f"{m.get('anchor', '?')}  ·  {m.get('filename', '')}"):
                st.write(h["text"])
    st.caption('The precedent question — "can we use Case X?" — runs through '
               "`src.analyze.precedent_test` once ANTHROPIC_API_KEY is set.")

with breakdown_tab:
    bd = st.session_state.get("breakdown")
    if not bd:
        st.info("Pick a case in the sidebar and click **Generate breakdown** "
                "(requires ANTHROPIC_API_KEY in .env).")
    else:
        meta = bd["metadata"]
        st.subheader(meta.get("case_no", ""))
        st.write(f"**Date:** {meta.get('date')}  ·  **Judges:** {', '.join(meta.get('judges', []))}")
        st.markdown(f"**Topics discussed:** {', '.join(bd.get('topics_discussed', [])) or '—'}")
        st.markdown("#### Facts")
        st.write(bd.get("factual_matrix"))
        st.markdown("#### Deciding factors")
        for d in bd.get("deciding_factors", []):
            st.markdown(f"- {d}")
        st.markdown("#### Case law cited")
        for p in bd.get("precedent_index", []):
            st.markdown(f"- *{p['cited_case']}* — **{p['treatment']}**")
        st.markdown("#### Final order")
        st.write(bd.get("final_order"))
        with st.expander("Full structured JSON"):
            st.json(bd)
