"""ROScribe — Scholar's Archive workspace (NiceGUI · Concept 2).

Layout (as requested):
  Left   — PDF      : the judgment document itself (inline viewer)
  Center — Breakdown: the CaseAnalysis (facts, issues, ratio, citations, statutes…)
  Right  — Query    : search judgements + notes; recent cases; click to open

Run (full corpus — uses .env):   .venv/bin/python app/workspace.py
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.config import REPO_ROOT, settings  # noqa: E402

from fastapi.responses import FileResponse, Response  # noqa: E402
from nicegui import app, run, ui  # noqa: E402

JUDGE_DIR = REPO_ROOT / "data" / "sc_judgements"


# --- inline PDF route: the browser DISPLAYS the file (never downloads) ---
@app.get("/pdf/{name}")
def serve_pdf(name: str):
    p = JUDGE_DIR / name
    if not p.exists():
        return Response(status_code=404)
    return FileResponse(
        str(p), media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{name}"'},
    )


# ------------------------------ data ------------------------------------- #
def _con() -> sqlite3.Connection:
    return sqlite3.connect(settings.sqlite_path)


def list_cases(limit: int = 60):
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


_NORM: dict[str, str] = {}


def find_case(cited: str) -> str | None:
    global _NORM
    if not _NORM:
        con = _con()
        _NORM = {re.sub(r"[^a-z0-9]", "", cn.lower()): cn for (cn,) in con.execute("SELECT case_no FROM judgements")}
        con.close()
    key = re.sub(r"[^a-z0-9]", "", (cited or "").lower())
    if key in _NORM:
        return _NORM[key]
    for k, cn in _NORM.items():
        if len(k) >= 9 and k in key:
            return cn
    return None


HEAD_CSS = """
<style>
  body { background:#f3f2ee; }
  .case-title { font-family: Georgia,'Times New Roman',serif; }
  .pane-head { font-size:.72rem; letter-spacing:.08em; text-transform:uppercase; color:#6b7280; font-weight:700; }
  .doc-pane { background:#fffdf7; }
  .sec { font-family:Georgia,serif; font-weight:700; color:#0f766e; margin-top:.7rem; margin-bottom:.1rem; }
</style>
"""


@ui.page("/")
def workspace():
    ui.add_head_html(HEAD_CSS)
    ui.colors(primary="#0f766e")
    state = {"case": None, "page": None}

    # ----------------------------- PDF (left) ----------------------------- #
    def render_pdf():
        pdf_pane.clear()
        with pdf_pane:
            if not state["case"]:
                ui.label("Open a case from the Query pane  →").classes("text-gray-400 mt-10 w-full text-center")
                return
            cn, _d, _parties, fn = state["case"]
            ui.label(cn).classes("text-sm font-bold case-title mb-1")
            src = f"/pdf/{fn}" + (f"#page={state['page']}" if state["page"] else "")
            ui.html(
                f'<iframe src="{src}" style="width:100%;height:calc(100vh - 120px);'
                'border:1px solid #e5e7eb;border-radius:6px"></iframe>'
            )

    # ------------------------- Breakdown (center) ------------------------- #
    def sec(t):
        ui.label(t).classes("sec")

    def para(t):
        ui.label(t or "—").classes("text-sm")

    async def gen_breakdown(cn):
        breakdown_pane.clear()
        with breakdown_pane:
            ui.label("Breakdown").classes("pane-head")
            with ui.row().classes("items-center gap-2 mt-3"):
                ui.spinner(size="lg")
                ui.label("Analysing with the local model… (~1 min on first run)").classes("text-sm")
        try:
            from src.analyze import analyze_case
            await run.io_bound(analyze_case, cn)
        except Exception as e:  # noqa: BLE001
            ui.notify(f"Breakdown failed: {e}", type="negative")
        render_breakdown()

    def render_breakdown():
        breakdown_pane.clear()
        with breakdown_pane:
            ui.label("Breakdown").classes("pane-head")
            if not state["case"]:
                ui.label("Select a case to see its analysis.").classes("text-gray-400 mt-2")
                return
            cn = state["case"][0]
            bd = get_breakdown(cn)
            if not bd:
                ui.label("No breakdown cached for this case.").classes("text-sm text-gray-500 mt-2")
                ui.button("⚡ Generate breakdown", on_click=lambda: gen_breakdown(cn)).props("color=primary")
                ui.label("Runs the local model once, then caches.").classes("text-xs text-gray-400 mt-1")
                return
            meta = bd.get("metadata", {})
            ui.label(cn).classes("text-xl font-bold case-title")
            ui.label(f"{meta.get('date', '')}   ·   {', '.join(meta.get('judges', []))}").classes("text-xs text-gray-500")
            if bd.get("topics_discussed"):
                with ui.row().classes("flex-wrap gap-1 mt-1"):
                    for t in bd["topics_discussed"][:10]:
                        ui.badge(t, color="teal").props("outline")
            sec("Facts")
            para(bd.get("factual_matrix"))
            if bd.get("legal_issues"):
                sec("Legal Issues")
                for li in bd["legal_issues"][:6]:
                    q = li.get("question") if isinstance(li, dict) else str(li)
                    ui.label(f"• {q}").classes("text-sm")
            sec("Ratio Decidendi")
            para(bd.get("ratio_decidendi"))
            if bd.get("deciding_factors"):
                sec("Deciding Factors")
                for d in bd["deciding_factors"][:8]:
                    ui.label(f"• {d}").classes("text-sm")
            if bd.get("precedent_index"):
                sec("Citations & Precedents")
                for p in bd["precedent_index"][:10]:
                    cited, tr = p.get("cited_case", ""), p.get("treatment", "")
                    target = find_case(cited)
                    label = f"• {cited}  [{tr}]"
                    if target:
                        ui.link(label, "#").classes("text-sm no-underline text-primary").on(
                            "click", lambda t=target: open_case(t)
                        )
                    else:
                        ui.label(label).classes("text-sm")
            if bd.get("legislation_cited"):
                sec("Legislation")
                for s in bd["legislation_cited"][:8]:
                    ui.label(f"• {s}").classes("text-sm")
            sec("Final Order")
            para(bd.get("final_order"))
            ui.separator().classes("my-2")
            ui.button("↻ Regenerate", on_click=lambda: gen_breakdown(cn)).props("flat dense color=primary")

    # --------------------------- Query (right) ---------------------------- #
    def open_case(case_no: str, page: int | None = None):
        row = case_by_no(case_no)
        if not row:
            ui.notify(f"Case not found: {case_no}", type="warning")
            return
        state["case"], state["page"] = row, page
        render_pdf()
        render_breakdown()

    def open_note(h: dict):
        with ui.dialog() as d, ui.card().classes("w-[640px]"):
            ui.label(h["meta"].get("case_no", "Note")).classes("font-semibold")
            ui.label(h["meta"].get("anchor", "")).classes("text-xs font-mono text-emerald-700")
            ui.separator()
            ui.label(h["text"][:1000]).classes("text-sm")
            ui.button("Close", on_click=d.close).props("flat")
        d.open()

    def show_recent():
        results.clear()
        with results:
            ui.label("Recent judgements").classes("text-xs text-gray-500 mb-1")
            with ui.list().props("separator").classes("w-full"):
                for cn, date, _p, _fn in list_cases():
                    with ui.item(on_click=lambda c=cn: open_case(c)).props("clickable"):
                        with ui.item_section():
                            ui.item_label(cn).classes("text-sm")
                            ui.item_label(date or "").props("caption")

    def show_hits(hits, query):
        results.clear()
        with results:
            ui.label(f'{len(hits)} results for "{query}"').classes("text-xs text-gray-500 mb-1")
            with ui.list().props("separator").classes("w-full"):
                for h in hits:
                    m = h["meta"]
                    note = m.get("source") == "personal_repo"
                    cb = (lambda hh=h: open_note(hh)) if note else (lambda c=m.get("case_no"), p=m.get("page"): open_case(c, p))
                    with ui.item(on_click=cb).props("clickable"):
                        with ui.item_section():
                            with ui.row().classes("items-center gap-1"):
                                ui.badge("NOTE" if note else "JUDGEMENT", color="green" if note else "blue").classes("text-[10px]")
                                ui.item_label(m.get("case_no", "")).classes("text-sm")
                            ui.item_label(h["text"][:90] + "…").props("caption")

    async def do_search(query):
        query = (query or "").strip()
        if not query:
            show_recent()
            return
        results.clear()
        with results:
            with ui.row().classes("items-center gap-2 mt-2"):
                ui.spinner()
                ui.label("Searching…").classes("text-sm")
        try:
            from src.retrieve import retrieve
            hits = await run.io_bound(retrieve, query, 16)
        except Exception as e:  # noqa: BLE001
            ui.notify(f"Search error: {e}", type="negative")
            show_recent()
            return
        show_hits(hits, query)

    # ------------------------------ layout -------------------------------- #
    with ui.header().classes("items-center justify-between bg-white text-gray-800 shadow-sm"):
        ui.label("⚖️  Sri Lankan Legal Insight Platform").classes("text-lg font-bold case-title")
        ui.badge("A.I. Active", color="green")

    with ui.row().classes("w-full no-wrap gap-0").style("height: calc(100vh - 56px)"):
        pdf_pane = ui.column().classes("w-2/5 h-full overflow-auto p-2 bg-white border-r")
        breakdown_pane = ui.column().classes("w-2/5 h-full overflow-auto p-3 doc-pane border-r")
        with ui.column().classes("w-1/5 h-full overflow-auto p-2 bg-white"):
            ui.label("Query").classes("pane-head")
            q = ui.input(placeholder="Search cases & notes…").props("outlined dense clearable").classes("w-full")
            ui.button("Search", on_click=lambda: do_search(q.value)).props("color=primary").classes("w-full")
            q.on("keydown.enter", lambda: do_search(q.value))
            results = ui.column().classes("w-full mt-2")

    show_recent()
    render_pdf()
    render_breakdown()
    init = list_cases(1)
    if init:
        open_case(init[0][0])


ui.run(host="127.0.0.1", port=8080, show=False, reload=False, title="ROScribe — Scholar's Archive")
