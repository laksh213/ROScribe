"""ROScribe — Streamlit prototype UI.

Run:  streamlit run app/streamlit_app.py

Sidebar: upload a Supreme Court judgment PDF.
Main:    structured CaseAnalysis output.

Skeleton only — the pipeline functions it will call are still stubs (src/).
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="ROScribe — SC Legal Research", layout="wide")
st.title("ROScribe · Supreme Court Legal Research")
st.caption("Citation-grounded RAG. Not legal advice — verify every citation.")

with st.sidebar:
    st.header("Ingest")
    st.file_uploader("Upload a judgment PDF", type=["pdf"])
    st.caption("Parsing not yet wired — see src/ingest.py (Phase 1).")

st.info(
    "Scaffold ready. Implement the pipeline in src/ "
    "(ingest → store → retrieve → analyze), then render the CaseAnalysis here."
)

query = st.text_input("Ask a question about the ingested case law")
if query:
    st.warning("Retrieval not yet implemented — see src/retrieve.py (Phase 3).")
