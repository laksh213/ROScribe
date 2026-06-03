"""Phase 5 — Grounded analysis & structured breakdown via Claude.

`analyze_pdf` extracts a judgment's text and asks Claude (with
prompts/system_prompt.md) for a `CaseAnalysis` JSON, validated against the
schema. `precedent_test` answers "can we use Case X?" using retrieved context.
Both enforce source-fidelity and `[Case No | Page:Para]` citations.

The system prompt is sent with prompt caching, so repeated calls are cheaper.

CLI:
  python -m src.analyze data/sc_judgements/<file>.pdf
"""

from __future__ import annotations

import argparse
import json
import sys

from .config import REPO_ROOT, settings
from .ingest import case_no_from_filename, extract_pages
from .schema import CaseAnalysis

PROMPT_PATH = REPO_ROOT / "prompts" / "system_prompt.md"


def _client():
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to .env to enable Claude analysis."
        )
    import anthropic

    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _system_block() -> list[dict]:
    return [{
        "type": "text",
        "text": PROMPT_PATH.read_text(),
        "cache_control": {"type": "ephemeral"},  # cache the long system prompt
    }]


def _extract_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found in the model response.")
    return json.loads(text[start : end + 1])


def analyze_text(case_no: str, full_text: str) -> CaseAnalysis:
    client = _client()
    user = (
        f"Case No: {case_no}\n\n"
        "Produce the case breakdown as ONE JSON object matching CaseAnalysis in "
        "src/schema.py. Use ONLY the judgment text below; for any field not present, "
        'use "Information not available in source text." Cite every claim as '
        "[Case No | Page:Para] using the page markers. Return ONLY the JSON.\n\n"
        f"=== JUDGMENT TEXT ===\n{full_text}"
    )
    resp = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=4096,
        system=_system_block(),
        messages=[{"role": "user", "content": user}],
    )
    return CaseAnalysis.model_validate(_extract_json(resp.content[0].text))


def analyze_pdf(pdf_path: str) -> CaseAnalysis:
    pages = extract_pages(pdf_path, ocr_langs=settings.tesseract_langs)
    text = "\n".join(f"===== Page {i} =====\n{t}" for i, t in enumerate(pages, 1))
    return analyze_text(case_no_from_filename(pdf_path), text)


def precedent_test(case_x: str, scenario: str, k: int = 8) -> str:
    """3-step precedent evaluation (retrieve -> compare -> validate vs notes)."""
    from .retrieve import retrieve

    context = retrieve(f"{case_x} {scenario}", k=k)
    snippets = "\n\n".join(f"{h['meta'].get('anchor', '?')}\n{h['text']}" for h in context)
    client = _client()
    user = (
        f"User scenario:\n{scenario}\n\nCandidate precedent: {case_x}\n\n"
        "Apply the Precedent Test (retrieve -> compare -> validate). Use ONLY the "
        "retrieved context; cite [Case No | Page:Para]; flag anything missing.\n\n"
        f"=== RETRIEVED CONTEXT ===\n{snippets}"
    )
    resp = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=2048,
        system=_system_block(),
        messages=[{"role": "user", "content": user}],
    )
    return resp.content[0].text


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Break down a judgment PDF with Claude.")
    ap.add_argument("pdf")
    args = ap.parse_args(argv)
    try:
        print(analyze_pdf(args.pdf).model_dump_json(indent=2))
    except RuntimeError as e:
        print(f"\n{e}\n", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
