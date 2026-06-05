"""ROScribe — Scholar's Archive workspace (NiceGUI · Concept 2).

Panes:
  Left   — PDF       : the judgment document (inline viewer)
  Center — Breakdown : reliable metadata (parties, bench) + LLM analysis;
                       topic chips are clickable -> related judgements
  Right  — Library   : live keyword search, By-Justice + By-area filters,
                       and judgements grouped by Year (default).
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.config import REPO_ROOT, settings  # noqa: E402
from src.ingest import extract_bench  # noqa: E402
from src.schema import NOT_AVAILABLE  # noqa: E402
from src.store import LEGAL_AREAS, area_search, keyword_search  # noqa: E402

from fastapi import Request  # noqa: E402
from fastapi.responses import FileResponse, RedirectResponse, Response  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402
from nicegui import Client, app, run, ui  # noqa: E402

JUDGE_DIR = REPO_ROOT / "data" / "sc_judgements"


@app.get("/pdf/{name}")
def serve_pdf(name: str):
    p = JUDGE_DIR / name
    if not p.exists():
        return Response(status_code=404)
    return FileResponse(str(p), media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{name}"'})


@app.get("/logo/{name}")
def serve_logo(name: str):
    p = REPO_ROOT / "data" / "logos" / name
    if not p.exists():
        return Response(status_code=404)
    return FileResponse(str(p))


# -------------------- access control (closed user base) ------------------ #
def _parse_users(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for pair in raw.split(","):
        if ":" in pair:
            u, p = pair.split(":", 1)
            out[u.strip()] = p.strip()
    return out


USERS = _parse_users(os.getenv("ROSCRIBE_USERS", ""))
STORAGE_SECRET = os.getenv("ROSCRIBE_STORAGE_SECRET", "roscribe-change-this-secret")
UNRESTRICTED = {"/login", "/demo"}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not app.storage.user.get("authenticated", False):
            if request.url.path in Client.page_routes.values() and request.url.path not in UNRESTRICTED:
                app.storage.user["referrer_path"] = request.url.path
                return RedirectResponse("/login")
        return await call_next(request)


app.add_middleware(AuthMiddleware)


@ui.page("/login", title="ROS", favicon="data/logos/logo_emblem.png")
def login():
    if app.storage.user.get("authenticated", False):
        return RedirectResponse("/")

    def attempt():
        if password.value and USERS.get(username.value) == password.value:
            app.storage.user.update({"username": username.value, "authenticated": True})
            ui.navigate.to(app.storage.user.get("referrer_path", "/"))
        else:
            ui.notify("Invalid credentials", color="negative")

    with ui.card().classes("absolute-center w-80 items-stretch"):
        ui.label("⚖️ ROScribe").classes("text-xl font-bold self-center")
        ui.label("Supreme Court of Sri Lanka — legal research").classes("text-xs text-gray-500 self-center mb-2")
        username = ui.input("Username").props("outlined dense").on("keydown.enter", attempt)
        password = ui.input("Password", password=True, password_toggle_button=True).props("outlined dense").on("keydown.enter", attempt)
        ui.button("Log in", on_click=attempt).props("color=primary")
        ui.button("Try the demo →", on_click=lambda: ui.navigate.to("/demo")).props("flat dense").classes("self-center")
    return None


# ------------------------------ data ------------------------------------- #
def _con() -> sqlite3.Connection:
    return sqlite3.connect(settings.sqlite_path)


def init_db():
    con = _con()
    con.execute("""
        CREATE TABLE IF NOT EXISTS bookmarks (
            username TEXT,
            case_no TEXT,
            PRIMARY KEY (username, case_no)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS annotations (
            username TEXT,
            case_no TEXT,
            notes TEXT,
            PRIMARY KEY (username, case_no)
        )
    """)
    con.commit()
    con.close()

init_db()


def is_bookmarked(user: str, case_no: str) -> bool:
    con = _con()
    row = con.execute("SELECT 1 FROM bookmarks WHERE username=? AND case_no=?", (user, case_no)).fetchone()
    con.close()
    return row is not None


def toggle_bookmark(user: str, case_no: str) -> bool:
    con = _con()
    if is_bookmarked(user, case_no):
        con.execute("DELETE FROM bookmarks WHERE username=? AND case_no=?", (user, case_no))
        status = False
    else:
        con.execute("INSERT OR REPLACE INTO bookmarks (username, case_no) VALUES (?, ?)", (user, case_no))
        status = True
    con.commit()
    con.close()
    return status


def get_bookmarks(user: str) -> list[str]:
    con = _con()
    rows = con.execute("SELECT case_no FROM bookmarks WHERE username=? ORDER BY case_no ASC", (user,)).fetchall()
    con.close()
    return [r[0] for r in rows]


def get_annotation(user: str, case_no: str) -> str:
    con = _con()
    row = con.execute("SELECT notes FROM annotations WHERE username=? AND case_no=?", (user, case_no)).fetchone()
    con.close()
    return row[0] if row else ""


def save_annotation(user: str, case_no: str, text: str):
    con = _con()
    con.execute("INSERT OR REPLACE INTO annotations (username, case_no, notes) VALUES (?, ?, ?)", (user, case_no, text))
    con.commit()
    con.close()


def get_citing_cases(case_no: str) -> list[str]:
    con = _con()
    rows = con.execute("SELECT case_no FROM analyses WHERE json LIKE ?", (f"%{case_no}%",)).fetchall()
    con.close()
    return [r[0] for r in rows if r[0] != case_no]


def _jl(s):
    try:
        return json.loads(s) if s else []
    except Exception:
        return []


def case_meta(case_no: str) -> dict:
    con = _con()
    row = con.execute(
        "SELECT case_no, date, parties, judges, keywords, legislation, filename "
        "FROM judgements WHERE case_no=? LIMIT 1", (case_no,)
    ).fetchone()
    con.close()
    if not row:
        return {}
    return {"case_no": row[0], "date": row[1] or "", "parties": row[2] or "",
            "judges": _jl(row[3]), "keywords": _jl(row[4]), "legislation": _jl(row[5]), "filename": row[6]}


_BENCH_CACHE: dict[str, list[str]] = {}


def bench_for(case_no: str, meta: dict) -> list[str]:
    """Full panel of judges for a case.

    The scrape only records the *authoring* judge, so we parse the real coram
    straight from the judgment text (`extract_bench`) and fall back to the
    scrape `judges` metadata when extraction finds nothing. Cached per case_no
    so each judgment is parsed at most once per process."""
    if case_no in _BENCH_CACHE:
        return _BENCH_CACHE[case_no]
    bench: list[str] = []
    fn = meta.get("filename")
    if fn:
        pdf = JUDGE_DIR / fn
        if pdf.exists():
            try:
                bench = extract_bench(str(pdf))
            except Exception:
                bench = []
    if not bench:
        bench = [j for j in (meta.get("judges") or []) if str(j).strip()]
    _BENCH_CACHE[case_no] = bench
    return bench


def get_breakdown(case_no: str):
    con = _con()
    row = con.execute("SELECT json FROM analyses WHERE case_no=?", (case_no,)).fetchone()
    con.close()
    return json.loads(row[0]) if row else None


def cases_by_judge(name: str) -> list[dict]:
    con = _con()
    rows = con.execute(
        "SELECT case_no, date, parties FROM judgements WHERE judges LIKE ? ORDER BY date DESC LIMIT 200",
        (f"%{name}%",)).fetchall()
    con.close()
    return [{"case_no": r[0], "date": r[1] or "", "snippet": (r[2] or "")[:100]} for r in rows]


def cases_by_keyword(area: str) -> list[dict]:
    con = _con()
    rows = con.execute(
        "SELECT case_no, date, parties FROM judgements WHERE keywords LIKE ? ORDER BY date DESC LIMIT 200",
        (f"%{area}%",)).fetchall()
    con.close()
    return [{"case_no": r[0], "date": r[1] or "", "snippet": (r[2] or "")[:100]} for r in rows]


_JUSTICES = None
_AREAS = None
_BY_YEAR = None
_NORM: dict[str, str] = {}


def distinct_justices() -> list[str]:
    global _JUSTICES
    if _JUSTICES is None:
        con = _con()
        names: set[str] = set()
        for (j,) in con.execute("SELECT judges FROM judgements WHERE judges IS NOT NULL AND judges!='[]'"):
            for n in _jl(j):
                n = n.strip()
                if n:
                    names.add(n)
        con.close()
        _JUSTICES = sorted(names)
    return _JUSTICES


def legal_areas() -> list[str]:
    return list(LEGAL_AREAS)  # curated real legal areas (see src/store.py)


def judgements_by_year() -> dict[str, list]:
    global _BY_YEAR
    if _BY_YEAR is None:
        con = _con()
        rows = con.execute("SELECT case_no, date FROM judgements").fetchall()
        con.close()
        by: dict[str, list] = {}
        for cn, date in rows:
            if date and date[:4].isdigit():
                y = date[:4]
            else:
                yrs = [int(x) for x in re.findall(r"(?:19|20)\d{2}", cn or "") if 1950 <= int(x) <= 2027]
                y = str(max(yrs)) if yrs else "Undated"
            by.setdefault(y, []).append((cn, date or ""))
        _BY_YEAR = by
    return _BY_YEAR


_BY_YEAR_MONTH = None
_MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def judgements_by_year_month() -> dict[str, dict[str, list]]:
    global _BY_YEAR_MONTH
    if _BY_YEAR_MONTH is None:
        con = _con()
        rows = con.execute("SELECT case_no, date FROM judgements").fetchall()
        con.close()
        by: dict[str, dict[str, list]] = {}
        for cn, date in rows:
            if date and date[:4].isdigit():
                y = date[:4]
            else:
                yrs = [int(x) for x in re.findall(r"(?:19|20)\d{2}", cn or "") if 1950 <= int(x) <= 2027]
                y = str(max(yrs)) if yrs else "Undated"
            
            m_name = "Unknown Month"
            if date and len(date) >= 7 and date[5:7].isdigit():
                m_idx = int(date[5:7]) - 1
                if 0 <= m_idx < 12:
                    m_name = _MONTH_NAMES[m_idx]
            
            by.setdefault(y, {}).setdefault(m_name, []).append((cn, date or ""))
        _BY_YEAR_MONTH = by
    return _BY_YEAR_MONTH


def find_case(cited: str):
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
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700&family=Lora:ital,wght@0,400;0,500;0,600;0,700;1,400&display=swap" rel="stylesheet">
<style>
  body {
    background: #f8f9fa;
    font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }
  .case-title {
    font-family: 'Plus Jakarta Sans', sans-serif;
  }
  .pane-head {
    font-size: 0.75rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #5f6368; /* Google Gray */
    font-weight: 700;
    margin-bottom: 4px;
  }
  .doc-pane {
    background: #ffffff;
  }
  .sec {
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 0.85rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #1a73e8; /* Google Blue */
    margin-top: 1.2rem;
    margin-bottom: 0.4rem;
  }
  .body-text {
    font-family: 'Lora', Georgia, serif;
    font-size: 0.92rem;
    line-height: 1.6;
    color: #3c4043;
  }
  .chip {
    cursor: pointer;
    border-radius: 6px;
    font-family: 'Plus Jakarta Sans', sans-serif;
  }
  .q-item:hover {
    background: #f1f3f4;
  }
  /* Google style scrollbar */
  ::-webkit-scrollbar {
    width: 6px;
    height: 6px;
  }
  ::-webkit-scrollbar-track {
    background: transparent;
  }
  ::-webkit-scrollbar-thumb {
    background: #dadce0;
    border-radius: 10px;
  }
  ::-webkit-scrollbar-thumb:hover {
    background: #bdc1c6;
  }
  /* Dark Mode specific overrides */
  .body--dark {
    background: #121212 !important;
    color: #e8eaed !important;
  }
  .body--dark .sec {
    color: #8ab4f8 !important;
  }
  .body--dark .pane-head {
    color: #9aa0a6 !important;
  }
  .body--dark .body-text {
    color: #e8eaed !important;
  }
  .body--dark ::-webkit-scrollbar-thumb {
    background: #3c4043;
  }
  .body--dark ::-webkit-scrollbar-thumb:hover {
    background: #5f6368;
  }
  .body--dark .bg-white {
    background-color: #1e1e1e !important;
  }
  .body--dark .bg-gray-100 {
    background-color: #121212 !important;
  }
  .body--dark .bg-gray-50 {
    background-color: #2c2c2c !important;
  }
  .body--dark .border {
    border-color: #2c2c2c !important;
  }
  .body--dark .text-gray-900 {
    color: #f1f3f4 !important;
  }
  .body--dark .text-gray-800 {
    color: #e8eaed !important;
  }
  .body--dark .text-gray-700 {
    color: #dadce0 !important;
  }
  .body--dark .text-gray-600 {
    color: #bdc1c6 !important;
  }
  .body--dark .text-gray-500 {
    color: #9aa0a6 !important;
  }
  /* responsive: 3 panes side-by-side on desktop; one at a time + tab bar on mobile */
  .mobile-tabs {
    display: none;
  }
  .panes-row {
    height: calc(100vh - 56px - 30px);
  }
  @media (max-width: 900px) {
    .mobile-tabs {
      display: flex;
    }
    .panes-row {
      height: calc(100vh - 56px - 48px - 30px);
      padding: 8px !important;
      gap: 8px !important;
    }
    .pane {
      display: none !important;
      width: 100% !important;
    }
    .pane.active {
      display: flex !important;
    }
    .hide-narrow {
      display: none !important;
    }
  }
</style>
""";

_TREAT_COLOR = {"Distinguished": "orange", "Overruled": "red", "Applied": "green", "Followed": "green"}


def build_workspace(demo: bool = False):
    ui.add_head_html(HEAD_CSS)
    ui.colors(primary="#1a73e8", secondary="#00796b")
    ui.dark_mode().disable()
    state = {"case": None, "page": None}
    containers = {"bookmarks": None}

    def refresh_bookmarks_ui():
        if not containers["bookmarks"]:
            return
        containers["bookmarks"].clear()
        username = app.storage.user.get("username", "anonymous")
        saved = get_bookmarks(username)
        if not saved:
            return
        with containers["bookmarks"]:
            exp = ui.expansion().classes("w-full mb-1").props("dense header-class='bg-blue-50 text-primary text-xs font-semibold rounded-md' expand-icon-class='text-primary'")
            with exp.add_slot('header'):
                with ui.row().classes("items-center justify-between w-full py-1.5 px-2"):
                    ui.label("Saved Bookmarks").classes("text-xs font-bold text-primary")
                    ui.badge(str(len(saved)), color="blue-2", text_color="primary").classes("text-[10px] px-2 py-0.5 rounded-full")
            
            with exp:
                with ui.column().classes("w-full pl-2 gap-1 py-1"):
                    for b_cn in saved:
                        with ui.row().classes("w-full items-center justify-between py-1.5 px-2 hover:bg-gray-100 rounded cursor-pointer transition-colors duration-150").on("click", lambda c=b_cn: open_case(c)):
                            ui.label(b_cn).classes("text-[11px] font-medium text-gray-800")

    # ----------------------------- PDF ------------------------------------ #
    def render_pdf():
        pdf_pane.clear()
        with pdf_pane:
            if not state["case"]:
                ui.label("Open a case from the Library  →").classes("text-gray-400 mt-10 w-full text-center")
                return
            cn, fn = state["case"]
            ui.label(cn).classes("text-sm font-bold case-title mb-1")
            src = f"/pdf/{fn}" + (f"#page={state['page']}" if state["page"] else "")
            ui.element("iframe").props(f'src="{src}"').classes("w-full").style(
                "height:calc(100vh - 120px);border:1px solid #e5e7eb;border-radius:6px")

    # --------------------------- Breakdown -------------------------------- #
    def sec(t):
        ui.label(t).classes("sec")

    def chips(items, color, text_color="white"):
        with ui.row().classes("flex-wrap gap-x-2.5 gap-y-3.5 mt-2 mb-3"):
            for it in items:
                ui.chip(it, on_click=lambda term=it: goto(term)).props(f"color={color} text-color={text_color} clickable").classes("cursor-pointer text-sm font-semibold px-3.5 py-1.5 rounded-full")

    def show_graph(cn):
        nodes = [{"id": cn, "label": cn, "color": "#1a73e8", "font": {"bold": True}, "size": 24}]
        edges = []
        
        bd = get_breakdown(cn)
        if bd and bd.get("precedent_index"):
            for p in bd["precedent_index"]:
                cited = p.get("cited_case")
                if cited and cited != NOT_AVAILABLE:
                    if not any(n["id"] == cited for n in nodes):
                        nodes.append({"id": cited, "label": cited, "color": "#00796b", "size": 16})
                    edges.append({"from": cn, "to": cited, "arrows": "to", "label": p.get("treatment", "")})
                    
        children = get_citing_cases(cn)
        for child in children:
            if not any(n["id"] == child for n in nodes):
                nodes.append({"id": child, "label": child, "color": "#d93025", "size": 16})
            edges.append({"from": child, "to": cn, "arrows": "to"})
            
        html_content = f"""
        <script type="text/javascript" src="https://cdnjs.cloudflare.com/ajax/libs/vis-network/9.1.2/standalone/umd/vis-network.min.js"></script>
        <div id="vis_graph" style="width:100%; height:440px; border:1px solid #e5e7eb; border-radius:8px; background-color:#f9fafb;"></div>
        <script>
            var nodes = new vis.DataSet({json.dumps(nodes)});
            var edges = new vis.DataSet({json.dumps(edges)});
            var container = document.getElementById('vis_graph');
            var data = {{ nodes: nodes, edges: edges }};
            var options = {{
                nodes: {{
                    shape: 'dot',
                    font: {{ size: 12, face: 'Plus Jakarta Sans', color: '#111827' }},
                    borderWidth: 2
                }},
                edges: {{
                    width: 1.5,
                    color: {{ color: '#9ca3af', highlight: '#1a73e8' }},
                    font: {{ size: 9, align: 'top', color: '#4b5563' }}
                }},
                physics: {{
                    stabilization: true,
                    barnesHut: {{
                        gravitationalConstant: -1500,
                        centralGravity: 0.3,
                        springLength: 95
                    }}
                }}
            }};
            var network = new vis.Network(container, data, options);
            network.on("doubleClick", function(params) {{
                if (params.nodes.length > 0) {{
                    var clickedNode = params.nodes[0];
                    var el = document.querySelector('.citation-graph-input input');
                    if (el) {{
                        el.value = clickedNode;
                        el.dispatchEvent(new Event('input'));
                    }}
                }}
            }});
        </script>
        """
        
        with ui.dialog() as dialog, ui.card().classes("w-[80vw] max-w-[800px] h-[540px] p-4"):
            with ui.row().classes("w-full items-center justify-between no-wrap mb-2"):
                ui.label(f"Precedent Map — {cn}").classes("text-sm font-bold text-gray-800")
                ui.button(icon="close", on_click=dialog.close).props("flat round dense color=grey-7")
            
            def on_node_select(e):
                if e.value:
                    open_case(e.value)
                    dialog.close()
            graph_input = ui.input(on_change=on_node_select).classes("citation-graph-input hidden")
            
            ui.html(html_content).classes("w-full h-[450px]")
            
        dialog.open()

    async def gen_breakdown(cn):
        client = breakdown_pane.client
        breakdown_pane.clear()
        with breakdown_pane:
            ui.label("Breakdown").classes("pane-head")
            with ui.row().classes("items-center gap-2 mt-3"):
                ui.spinner(size="lg")
                ui.label("Analysing with the local model… (~1–2 min)").classes("text-sm")
        try:
            from src.analyze import analyze_case
            await run.io_bound(analyze_case, cn)
        except Exception as e:  # noqa: BLE001
            try:
                client.outbox.enqueue_message('notify', {'message': f"Breakdown failed: {e}", 'type': 'negative'}, client.id)
            except Exception:
                print(f"Breakdown failed: {e}")
        finally:
            render_breakdown()

    def render_breakdown():
        breakdown_pane.clear()
        with breakdown_pane:
            ui.label("Analysis & Breakdown").classes("pane-head")
            if not state["case"]:
                ui.label("Select a case from the library to view its analysis.").classes("text-gray-400 mt-4 text-sm")
                return
            
            cn = state["case"][0]
            m = case_meta(cn)
            
            bench = bench_for(cn, m)
            authoring_judges = m.get("judges") or []
            decided_date = m.get("date") or "Date not available"
            
            bench_str = ", ".join(bench) if bench else "Bench information not available in source"
            authoring_str = ", ".join(authoring_judges) if authoring_judges else "Authoring judge not specified"
            
            username = app.storage.user.get("username", "anonymous")
            bookmarked = is_bookmarked(username, cn)

            # --- Google Material Header Card ---
            with ui.card().classes("w-full p-4 mb-4").style("border-radius: 12px; border: 1px solid #dadce0; box-shadow: none; background: #ffffff;"):
                # Bookmark Toggle Row
                with ui.row().classes("w-full items-center justify-between no-wrap mb-2"):
                    ui.label("Case Information").classes("text-[10px] uppercase tracking-wider font-bold text-gray-400")
                    def on_bookmark():
                        status = toggle_bookmark(username, cn)
                        bookmark_btn.props(f"icon={'bookmark' if status else 'bookmark_border'}")
                        ui.notify("Added to Bookmarks" if status else "Removed from Bookmarks", color="primary" if status else "grey-7")
                        refresh_bookmarks_ui()
                    bookmark_btn = ui.button(on_click=on_bookmark).props(f"flat round dense icon={'bookmark' if bookmarked else 'bookmark_border'} color=primary").classes("text-sm")
                
                # Bench (Coram) - FIRST
                with ui.row().classes("items-start gap-2 mt-1 w-full no-wrap"):
                    ui.icon("gavel", size="18px", color="primary").classes("mt-0.5 w-5 text-center flex-shrink-0")
                    with ui.column().classes("gap-0.5"):
                        ui.label("Bench (Coram)").classes("text-[10px] uppercase tracking-wider font-bold text-gray-400")
                        ui.label(bench_str).classes("text-xs font-semibold text-gray-800")
                
                # Authoring Judge - SECOND
                with ui.row().classes("items-start gap-2 mt-2 w-full no-wrap"):
                    ui.icon("edit_note", size="18px", color="secondary").classes("mt-0.5 w-5 text-center flex-shrink-0")
                    with ui.column().classes("gap-0.5"):
                        ui.label("Judgement Delivered By").classes("text-[10px] uppercase tracking-wider font-bold text-gray-400")
                        ui.label(authoring_str).classes("text-xs font-semibold text-gray-800")

                # Decided Date - THIRD
                with ui.row().classes("items-start gap-2 mt-2 w-full no-wrap"):
                    ui.icon("calendar_today", size="18px", color="grey-6").classes("mt-0.5 w-5 text-center flex-shrink-0")
                    with ui.column().classes("gap-0.5"):
                        ui.label("Decided On").classes("text-[10px] uppercase tracking-wider font-bold text-gray-400")
                        ui.label(decided_date).classes("text-xs font-semibold text-gray-800")

                ui.separator().classes("my-3")

                # Parties - THIRD (reduced size)
                if m.get("parties") and m["parties"] != NOT_AVAILABLE:
                    with ui.column().classes("gap-0.5"):
                        ui.label("Parties").classes("text-[10px] uppercase tracking-wider font-bold text-gray-400")
                        ui.label(m["parties"]).classes("text-xs font-medium text-gray-700 leading-normal case-title")
            
            if m.get("keywords"):
                ui.label("Keywords").classes("text-[10px] uppercase font-bold tracking-wider text-gray-400 mt-2 pl-1")
                chips(m["keywords"][:14], "blue-9")

            bd = get_breakdown(cn)
            if not bd:
                # Basic metadata fallback
                with ui.card().classes("w-full p-4 mt-2").style("border-radius: 12px; border: 1px solid #dadce0; box-shadow: none;"):
                    if m.get("legislation"):
                        sec("Legislation")
                        for s in m["legislation"][:10]:
                            ui.label(f"• {s}").classes("text-sm body-text")
                    
                    ui.separator().classes("my-3")
                    if demo:
                        ui.label("🔒 Full AI analysis (facts · issues · ratio · precedents) is available after login.").classes("text-sm text-gray-500 mb-2")
                        ui.button("Log in to Unlock", on_click=lambda: ui.navigate.to("/login")).props("color=primary rounded unevaluated")
                    else:
                        ui.button("⚡ Generate AI analysis", on_click=lambda: gen_breakdown(cn)).props("color=primary rounded")
                        ui.label("Extracts facts, ratio, citations, and legislation using the local GGUF model.").classes("text-xs text-gray-400 mt-2")
                return

            if bd.get("topics_discussed"):
                ui.label("Topics Discussed").classes("text-[10px] uppercase font-bold tracking-wider text-gray-400 mt-2 pl-1")
                chips(bd["topics_discussed"][:10], "indigo-9")
            
            # Detailed AI Analysis blocks styled as neat cards
            with ui.card().classes("w-full p-4 mt-3").style("border-radius: 12px; border: 1px solid #dadce0; box-shadow: none;"):
                sec("Facts / Factual Matrix")
                ui.label(bd.get("factual_matrix") or "—").classes("body-text mb-3")
                
                if bd.get("legal_issues"):
                    sec("Legal Issues")
                    for li in bd["legal_issues"][:6]:
                        ui.label(f"• {li.get('question') if isinstance(li, dict) else li}").classes("body-text pl-2 mb-1")
                

                
                sec("Ratio Decidendi")
                ui.label(bd.get("ratio_decidendi") or "—").classes("body-text mb-3")
                
                if bd.get("deciding_factors"):
                    sec("Deciding Factors")
                    for d in bd["deciding_factors"][:8]:
                        ui.label(f"• {d}").classes("body-text pl-2 mb-1")
                
                if bd.get("precedent_index"):
                    with ui.row().classes("w-full items-center justify-between no-wrap"):
                        sec("Citations & Distinctions")
                        ui.button("Visual Map", on_click=lambda: show_graph(cn)).props("flat dense color=primary icon=bubble_chart").classes("text-xs")
                    for p in bd["precedent_index"][:12]:
                        cited, tr = p.get("cited_case", ""), p.get("treatment", "")
                        target = find_case(cited)
                        with ui.row().classes("items-center gap-2 py-1 no-wrap pl-2"):
                            if tr and tr != NOT_AVAILABLE:
                                ui.badge(tr, color="blue-2" if tr in ("Applied", "Followed") else "amber-2", text_color="grey-9").classes("text-[10px] px-2 py-0.5 rounded")
                            if target:
                                ui.link(cited, "#").classes("text-xs font-semibold no-underline text-primary").on("click", lambda t=target: open_case(t))
                            else:
                                ui.label(cited).classes("text-xs text-gray-700")
                
                leg = list(dict.fromkeys((m.get("legislation") or []) + (bd.get("legislation_cited") or [])))
                if leg:
                    sec("Legislation Cited")
                    for s in leg[:10]:
                        ui.label(f"• {s}").classes("body-text pl-2 mb-1")
                
                sec("Final Order")
                ui.label(bd.get("final_order") or "—").classes("body-text mb-2")
                
                if not demo and bd.get("academic_synthesis") and bd["academic_synthesis"] != NOT_AVAILABLE:
                    sec("Scholar's Note")
                    ui.label(bd["academic_synthesis"]).classes("body-text mb-2")
                
                if not demo:
                    with ui.row().classes("w-full justify-end items-center"):
                        ui.button("Regenerate Analysis", on_click=lambda: gen_breakdown(cn)).props("flat dense color=primary icon=refresh").classes("text-xs")

    # ----------------------------- navigation ----------------------------- #
    def open_case(case_no, page=None):
        con = _con()
        row = con.execute("SELECT case_no, filename FROM judgements WHERE case_no=? LIMIT 1", (case_no,)).fetchone()
        con.close()
        if not row:
            ui.notify(f"Case not found: {case_no}", type="warning")
            return
        state["case"], state["page"] = row, page
        render_pdf()
        render_breakdown()
        set_active("bd")  # mobile: jump to the analysis when a case opens

    # ----------------------------- Library -------------------------------- #
    def make_year(y, months_dict):
        total_cases = sum(len(cases) for cases in months_dict.values())
        exp = ui.expansion().classes("w-full mb-1").props("dense header-class='bg-gray-50 text-gray-700 text-xs font-semibold rounded-md' expand-icon-class='text-gray-400'")
        with exp.add_slot('header'):
            with ui.row().classes("items-center justify-between w-full py-1.5 px-2"):
                ui.label(y).classes("text-xs font-bold text-gray-700")
                ui.badge(str(total_cases), color="grey-3", text_color="grey-8").classes("text-[10px] px-2 py-0.5 rounded-full")

        loaded = {"v": False}

        def load():
            if loaded["v"] or not exp.value:
                return
            loaded["v"] = True
            with exp:
                with ui.column().classes("w-full pl-2 gap-1 py-1"):
                    def month_sort_key(m_name):
                        try:
                            return _MONTH_NAMES.index(m_name)
                        except ValueError:
                            return 12

                    sorted_months = sorted(months_dict.keys(), key=month_sort_key)
                    for m_name in sorted_months:
                        cases = months_dict[m_name]
                        if not cases:
                            continue

                        # Sub-expansion for each Month
                        m_exp = ui.expansion().classes("w-full pl-1 mb-0.5").props("dense header-class='text-gray-600 text-[11px] font-medium' expand-icon-class='text-gray-400'")
                        with m_exp.add_slot('header'):
                            with ui.row().classes("items-center justify-between w-full py-1 px-1"):
                                ui.label(m_name).classes("text-[11px] font-semibold text-gray-600")
                                ui.badge(str(len(cases)), color="grey-2", text_color="grey-6").classes("text-[9px] px-1.5 py-0.2 rounded-full")

                        with m_exp:
                            with ui.column().classes("w-full pl-2 gap-1 py-1"):
                                for cn, _date in sorted(cases, key=lambda c: c[1], reverse=True):
                                    with ui.row().classes("w-full items-center justify-between py-1.5 px-2 hover:bg-gray-100 rounded cursor-pointer transition-colors duration-150").on("click", lambda c=cn: open_case(c)):
                                        ui.label(cn).classes("text-[11px] font-medium text-gray-800")
                                        if _date:
                                            ui.label(_date).classes("text-[9px] text-gray-400")

        exp.on_value_change(load)

    def show_tree():
        results.clear()
        with results:
            ui.label("Browse by Year & Month").classes("text-xs font-semibold text-gray-500 mb-2 mt-1")
            by = judgements_by_year_month()
            years = sorted((y for y in by if y != "Undated"), reverse=True)
            if "Undated" in by:
                years.append("Undated")
            for y in years:
                make_year(y, by[y])

    def show_results(hits, label):
        results.clear()
        with results:
            with ui.row().classes("items-center justify-between w-full mb-2"):
                ui.label(label).classes("text-xs font-semibold text-gray-500")
                ui.button("Reset Filters", on_click=reset).props("flat dense color=primary icon=restart_alt").classes("text-xs")
            if not hits:
                ui.label("No judgements match these criteria.").classes("text-sm text-gray-500 mt-2")
                return
            for h in hits:
                cn = h["case_no"]
                dt = h.get("date", "")
                snip = h.get("snippet", "")
                with ui.card().classes("w-full p-3 mb-2 cursor-pointer hover:shadow-md transition-shadow duration-200").on("click", lambda c=cn: open_case(c)).style("border-radius: 8px; border: 1px solid #e8eaed; box-shadow: none;"):
                    with ui.row().classes("justify-between items-center w-full no-wrap"):
                        ui.label(cn).classes("text-xs font-bold text-primary truncate").style("max-width: 70%;")
                        if dt:
                            ui.badge(dt[:4], color="blue-1", text_color="primary").classes("text-[10px] px-2 py-0.5").style("border-radius: 4px; box-shadow: none;")
                    if snip:
                        ui.label(snip).classes("text-[11px] text-gray-600 mt-1 line-clamp-2")

    def run_search(term):
        term = (term or "").strip()
        if not term:
            show_tree()
            return
        hits = keyword_search(term, 80)
        show_results(hits, f'{len(hits)} results · "{term}"')

    def goto(term):
        """Jump the Library to a topic/keyword (clicked from the breakdown)."""
        q.value = term
        run_search(term)
        set_active("library")  # mobile: show the related results

    def filter_judge(name):
        if not name:
            show_tree()
            return
        hits = cases_by_judge(name)
        show_results(hits, f"Justice {name} · {len(hits)} cases")

    def filter_area(area):
        if not area:
            show_tree()
            return
        hits = area_search(area)
        show_results(hits, f"{area} · {len(hits)} cases")

    def reset():
        q.value = ""
        show_tree()

    # ------------------------------ layout -------------------------------- #
    with ui.header().classes("items-center justify-between bg-white text-gray-900 border-b shadow-none").style("border-color: #dadce0; height: 56px;"):
        # Left side containing AI Active and Logout/Login
        with ui.row().classes("items-center gap-3"):
            if demo:
                ui.badge("DEMO · read-only", color="orange").classes("px-3 py-1 text-xs font-semibold").style("border-radius: 6px; box-shadow: none;")
                ui.button("Log in", on_click=lambda: ui.navigate.to("/login")).props("flat dense color=primary").classes("text-xs font-semibold")
            else:
                ui.badge("A.I. Active", color="green").classes("px-3 py-1 text-xs font-semibold").style("border-radius: 6px; box-shadow: none;")
                ui.button(icon="logout", on_click=lambda: (app.storage.user.clear(), ui.navigate.to("/login"))).props("flat round dense color=grey-7").classes("hover:bg-gray-100")
        
        # Middle title "ROS" styled fancy
        ui.label("ROS").classes("absolute-center text-2xl font-bold").style("font-family: 'Lora', Georgia, serif; letter-spacing: 0.25em; color: #0f2d59;")

    # mobile-only tab switcher (hidden on desktop via CSS)
    tab_btns: dict = {}
    with ui.row().classes("mobile-tabs w-full items-stretch gap-0 bg-white border-b shadow-none").style("border-color: #dadce0;"):
        for key, label, icon in [("library", "Library", "menu_book"), ("bd", "Breakdown", "gavel"), ("pdf", "Document", "description")]:
            tab_btns[key] = ui.button(label, icon=icon, on_click=lambda k=key: set_active(k)).props("flat no-caps dense").classes("flex-grow")

    with ui.row().classes("panes-row w-full no-wrap gap-3 p-3 bg-gray-100"):
        pdf_pane = ui.column().classes("pane w-2/5 h-full overflow-auto p-4 bg-white border rounded-xl shadow-sm")
        breakdown_pane = ui.column().classes("pane w-2/5 h-full overflow-auto p-4 bg-white border rounded-xl shadow-sm")
        library = ui.column().classes("pane w-1/5 h-full overflow-auto p-4 bg-white border rounded-xl shadow-sm gap-3")
        with library:
            ui.label("Library").classes("pane-head")
            containers["bookmarks"] = ui.column().classes("w-full mb-1")
            
            # Google Search Input style
            q = ui.input(placeholder="Search parties, phrases, case no…",
                         on_change=lambda e: run_search(e.value)).props("rounded outlined dense clearable").classes("w-full")
            with q.add_slot('prepend'):
                ui.icon("search").classes("text-gray-400")
            q.on("keydown.enter", lambda: run_search(q.value))
            
            # Quick filter areas chips (horizontal scroll)
            ui.label("Quick Filters").classes("text-[10px] uppercase font-bold tracking-wider text-gray-400 mt-1")
            with ui.scroll_area().classes("w-full h-8 mb-1"):
                with ui.row().classes("no-wrap gap-1"):
                    popular_areas = ["Fundamental Rights", "Land & Property", "Contract", "Criminal Law", "Civil Procedure"]
                    for pa in popular_areas:
                        ui.chip(pa, color="blue-1", on_click=lambda term=pa: filter_area(term)).props("outline clickable dense").classes("text-[10px] font-semibold text-primary")
            
            judge_sel = ui.select(distinct_justices(), label="By Justice", with_input=True, clearable=True,
                                  on_change=lambda e: filter_judge(e.value)).props("outlined dense rounded").classes("w-full")
            area_sel = ui.select(legal_areas(), label="By legal area", with_input=True, clearable=True,
                                 on_change=lambda e: filter_area(e.value)).props("outlined dense rounded").classes("w-full")
            results = ui.column().classes("w-full")

    with ui.footer().classes("items-center justify-center bg-white border-t p-1 shadow-none").style("height: 30px; border-color: #dadce0;"):
        ui.label("built by SMS").classes("text-[10px] text-gray-500 font-semibold uppercase tracking-wider")

    def set_active(name):
        for k, pane in {"pdf": pdf_pane, "bd": breakdown_pane, "library": library}.items():
            pane.classes(add="active") if k == name else pane.classes(remove="active")
        for k, btn in tab_btns.items():
            btn.props(f"color={'primary' if k == name else 'grey-6'}")

    show_tree()
    refresh_bookmarks_ui()
    render_pdf()
    render_breakdown()
    init = judgements_by_year()
    newest = sorted((y for y in init if y != "Undated"), reverse=True)
    if newest:
        cases = sorted(init[newest[0]], key=lambda c: c[1], reverse=True)
        if cases:
            open_case(cases[0][0])
    set_active("library")  # default visible pane on mobile (desktop shows all 3)


@ui.page("/", title="ROS", favicon="data/logos/logo_emblem.png")
def home():
    build_workspace(demo=False)


@ui.page("/demo", title="ROS", favicon="data/logos/logo_emblem.png")
def demo_page():
    build_workspace(demo=True)


ui.run(host="127.0.0.1", port=8080, show=False, reload=False,
       storage_secret=STORAGE_SECRET, title="ROS", favicon="data/logos/logo_emblem.png")
