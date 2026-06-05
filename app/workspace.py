"""ROScribe — Scholar's Archive workspace (NiceGUI · Concept 2).

Three panes:
  Left   — Explorer : global search across judgements + your notes
  Center — Document : case info, PDF reader (jump-to-page), Academic Cross-Reference
  Right  — Intelligence : CaseAnalysis (ratio, clickable citations, statutes, terms),
           generated on demand and cached.

Run (full corpus — uses .env):   .venv/bin/python app/workspace.py
Run (isolated dev sandbox):
  SQLITE_PATH=/tmp/roscribe_dev/dev.db CHROMA_DIR=/tmp/roscribe_dev/chroma \
  ROSCRIBE_EMBEDDER=default .venv/bin/python app/workspace.py
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.config import REPO_ROOT, settings  # noqa: E402
from src.retrieve import retrieve  # noqa: E402

from nicegui import app, run, ui  # noqa: E402

app.add_static_files("/pdfs", str(REPO_ROOT / "data" / "sc_judgements"))
ui.colors(primary="#0f766e")
ui.add_head_html("""
<style>
  body { background:#f3f2ee; }
  .case-title { font-family: Georgia,'Times New Roman',serif; }
  .pane-head { font-size:.7rem; letter-spacing:.08em; text-transform:uppercase; color:#6b7280; font-weight:700; }
  .doc-pane { background:#fffdf7; }
  .sec { font-family:Georgia,serif; font-weight:700; color:#0f766e; margin-top:.7rem; }
  .reslist .q-card { transition: background .1s; }
</style>
""")


# ------------------------------ data ------------------------------------- #
def _con() -> sqlite3.Connection:
    return sqlite3.connect(settings.sqlite_path)


def list_cases(limit: int = 80):
    con = _con()
    rows = con.execute(
        "SELECT case_no, date, parties, filename FROM judgements ORDER BY date DESC LIMIT ?", (limit,)
    ).fetchall()
    con.close()
    return rows


def case_by_no(case_no: str):
    con = _con()
    row = con.execute(
        "SELECT case_no, date, parties, filename FROM judgements WHERE case_no=? LIMIT 1", (case_no,)
    ).fetchone()
    con.close()
    return row


def get_breakdown(case_no: str):
    con = _con()
    row = con.execute("SELECT json FROM analyses WHERE case_no=?", (case_no,)).fetchone()
    con.close()
    return json.loads(row[0]) if row else None


_NORM_MAP: dict[str, str] = {}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def find_case(cited: str) -> str | None:
    """Match a free-text citation to a case_no in the corpus (for click-to-jump)."""
    global _NORM_MAP
    if not _NORM_MAP:
        con = _con()
        _NORM_MAP = {_norm(cn): cn for (cn,) in con.execute("SELECT case_no FROM judgements")}
        con.close()
    key = _norm(cited)
    if key in _NORM_MAP:
        return _NORM_MAP[key]
    for k, cn in _NORM_MAP.items():        # substring fallback (e.g. "SC Appeal 175/2017")
        if len(k) >= 8 and (k in key or key in k):
            return cn
    return None


class S:
    left = center = right = None
    current = None
    page = None


state = S()


# --------------------- Academic Cross-Reference -------------------------- #
def cross_reference(term: str):
    term = (term or "").strip()
    if not term:
        return
    hits = retrieve(term, k=3, source="personal_repo")
    with ui.dialog() as dialog, ui.card().classes("w-[640px]"):
        ui.label(f'Academic Cross-Reference — "{term}"').classes("text-lg font-semibold")
        ui.label("Pulled from your personal notes repository").classes("text-xs text-gray-500")
        ui.separator()
        if not hits:
            ui.label("No matching notes found.").classes("text-sm")
        for h in hits:
            with ui.card().classes("w-full bg-emerald-50 border border-emerald-100"):
                ui.label(h["meta"].get("anchor", "")).classes("text-xs font-mono text-emerald-700")
                t = h["text"]
                ui.label(t[:600] + ("…" if len(t) > 600 else "")).classes("text-sm")
        ui.button("Close", on_click=dialog.close).props("flat")
    dialog.open()


def open_note(h: dict):
    with ui.dialog() as d, ui.card().classes("w-[640px]"):
        ui.label(h["meta"].get("case_no", "Note")).classes("font-semibold")
        ui.label(h["meta"].get("anchor", "")).classes("text-xs font-mono text-emerald-700")
        ui.separator()
        ui.label(h["text"][:1000]).classes("text-sm")
        ui.button("Close", on_click=d.close).props("flat")
    d.open()


# ------------------------------ panes ------------------------------------ #
def render_results(query: str):
    state.left.clear()
    with state.left:
        ui.label("Explorer").classes("pane-head mb-1")
        query = (query or "").strip()
        if query:
            hits = retrieve(query, k=16)
            ui.label(f'{len(hits)} results for "{query}"').classes("text-xs text-gray-500 mb-1")
            with ui.column().classes("reslist w-full gap-1"):
                for h in hits:
                    m = h["meta"]
                    note = m.get("source") == "personal_repo"
                    page = m.get("page")
                    cb = (lambda hh=h: open_note(hh)) if note else (lambda cn=m.get("case_no"), p=page: load_case(cn, p))
                    with ui.card().classes("w-full cursor-pointer hover:bg-gray-50 p-2").on("click", cb):
                        ui.badge("NOTE" if note else "JUDGEMENT", color="green" if note else "blue").classes("text-[10px]")
                        ui.label(m.get("case_no", "")).classes("text-sm font-medium leading-tight")
                        ui.label(h["text"][:110] + "…").classes("text-xs text-gray-500")
        else:
            ui.label("Recent judgements").classes("text-xs text-gray-500 mb-1")
            with ui.column().classes("reslist w-full gap-1"):
                for cn, date, _p, _fn in list_cases():
                    with ui.card().classes("w-full cursor-pointer hover:bg-gray-50 p-2").on("click", lambda c=cn: load_case(c)):
                        ui.label(cn).classes("text-sm font-medium leading-tight")
                        ui.label(date or "").classes("text-xs text-gray-500")


def load_case(case_no: str, page: int | None = None):
    row = case_by_no(case_no)
    if row:
        state.current = row
        state.page = page
        render_center()
        render_right()


def render_center():
    state.center.clear()
    with state.center:
        if not state.current:
            ui.label("Select a case from the Explorer to open it.").classes("text-gray-400 mt-10 w-full text-center")
            return
        cn, _date, parties, fn = state.current
        with ui.row().classes("items-center justify-between w-full"):
            ui.label(cn).classes("text-xl font-bold case-title")
            ui.badge("Precedential Status: Applied", color="teal")
        ui.label((parties or "")[:220]).classes("text-xs text-gray-500")
        with ui.row().classes("items-center gap-2 my-2 w-full"):
            term = ui.input(placeholder="Cross-reference a legal term (e.g. constructive trust)…").props("dense outlined").classes("flex-grow")
            ui.button("Look up in my notes", on_click=lambda: cross_reference(term.value)).props("color=primary")
        src = f"/pdfs/{fn}" + (f"#page={state.page}" if state.page else "")
        ui.html(f'<iframe src="{src}" style="width:100%;height:62vh;border:1px solid #e5e7eb;border-radius:8px"></iframe>')


async def _generate(cn: str):
    state.right.clear()
    with state.right:
        ui.label("Intelligence").classes("pane-head")
        with ui.row().classes("items-center gap-2 mt-3"):
            ui.spinner(size="lg")
            ui.label("Analysing with local model… (~1 min on first run)").classes("text-sm")
    try:
        from src.analyze import analyze_case
        await run.io_bound(analyze_case, cn)
    except Exception as e:  # noqa: BLE001
        ui.notify(f"Breakdown failed: {e}", type="negative")
    render_right()


def render_right():
    state.right.clear()
    with state.right:
        ui.label("Intelligence").classes("pane-head")
        if not state.current:
            ui.label("—").classes("text-gray-400")
            return
        cn = state.current[0]
        bd = get_breakdown(cn)
        if not bd:
            ui.label("No breakdown cached for this case.").classes("text-sm text-gray-500 mt-2")
            ui.button("⚡ Generate breakdown", on_click=lambda: _generate(cn)).props("color=primary")
            ui.label("Runs the local model once, then caches.").classes("text-xs text-gray-400 mt-1")
            return

        ui.label("Ratio Decidendi").classes("sec")
        ui.label(bd.get("ratio_decidendi", "—")).classes("text-sm")

        ui.label("Citations & Precedents").classes("sec")
        for p in bd.get("precedent_index", [])[:10]:
            cited = p.get("cited_case", "")
            target = find_case(cited)
            label = f"• {cited}  [{p.get('treatment', '')}]"
            if target:
                ui.link(label, "#").classes("text-sm text-primary no-underline").on(
                    "click", lambda t=target: load_case(t)
                )
            else:
                ui.label(label).classes("text-sm")

        if bd.get("legislation_cited"):
            ui.label("Related Statutory Links").classes("sec")
            for s in bd["legislation_cited"][:8]:
                ui.label(f"• {s}").classes("text-sm")

        if bd.get("topics_discussed"):
            ui.label("Related Terms").classes("sec")
            with ui.row().classes("flex-wrap gap-1"):
                for t in bd["topics_discussed"][:12]:
                    ui.badge(t, color="teal").props("outline").classes("cursor-pointer").on(
                        "click", lambda term=t: cross_reference(term)
                    )

        ui.separator().classes("my-3")
        ui.button("↻ Regenerate", on_click=lambda: _generate(cn)).props("flat dense color=primary")


# ------------------------------ layout ----------------------------------- #
with ui.header().classes("items-center justify-between bg-white text-gray-800 shadow-sm"):
    ui.label("⚖️  Sri Lankan Legal Insight Platform").classes("text-lg font-bold case-title")
    search = ui.input(placeholder="Search judgements & notes…").props("outlined dense clearable").classes("w-1/2")
    search.on("keydown.enter", lambda: render_results(search.value))
    ui.badge("A.I. Active", color="green")

with ui.row().classes("w-full no-wrap gap-0").style("height: calc(100vh - 56px)"):
    state.left = ui.column().classes("w-1/4 h-full overflow-auto border-r p-2 bg-white")
    state.center = ui.column().classes("w-1/2 h-full overflow-auto p-3 doc-pane")
    state.right = ui.column().classes("w-1/4 h-full overflow-auto border-l p-3 bg-white")

render_results("")
_initial = list_cases(1)
if _initial:
    load_case(_initial[0][0])
else:
    render_center()
    render_right()

ui.run(host="127.0.0.1", port=8080, show=False, reload=False, title="ROScribe — Scholar's Archive")
