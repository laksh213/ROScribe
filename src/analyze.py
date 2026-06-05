"""Phase 5 — Grounded analysis & structured breakdown.

The LLM is pluggable via LLM_PROVIDER (see config / .env):
  - "ollama"    local, OpenAI-compatible endpoint (default; private, zero-cost)
  - "anthropic" Claude (highest quality / best schema adherence)
  - "openai"    OpenAI or any OpenAI-compatible API

`analyze_pdf` extracts a judgment and returns a validated `CaseAnalysis`.
`precedent_test` answers "can we use Case X?" using retrieved context (and your
notes, when indexed). Both enforce source-fidelity and `[Case No | Page:Para]`
citations.

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

_LLAMA = None


def _get_llama():
    """Lazy-load a local GGUF via llama-cpp-python (cached for the process)."""
    global _LLAMA
    if _LLAMA is None:
        from llama_cpp import Llama

        _LLAMA = Llama(
            model_path=settings.llamacpp_model_path,
            n_ctx=settings.ollama_num_ctx,
            n_gpu_layers=-1,  # offload to Metal where available
            verbose=False,
        )
    return _LLAMA


def _chat(system_text: str, user_text: str, max_tokens: int = 4096, json_mode: bool = False) -> str:
    """Dispatch one chat completion to the configured provider; return raw text."""
    provider = settings.llm_provider.lower()

    if provider == "anthropic":
        if not settings.anthropic_api_key:
            raise RuntimeError("LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set.")
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_text}],
        )
        return resp.content[0].text

    if provider == "llamacpp":
        llm = _get_llama()
        kwargs: dict = {
            "messages": [
                {"role": "system", "content": system_text},
                {"role": "user", "content": user_text},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.1 if json_mode else 0.5,  # low temp = consistent structure
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        return llm.create_chat_completion(**kwargs)["choices"][0]["message"]["content"]

    # OpenAI-compatible: Ollama (local) or OpenAI
    from openai import OpenAI

    if provider == "ollama":
        client = OpenAI(base_url=settings.ollama_base_url, api_key="ollama", timeout=600.0)
        model = settings.llm_model
    elif provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("LLM_PROVIDER=openai but OPENAI_API_KEY is not set.")
        client = OpenAI(api_key=settings.openai_api_key, timeout=600.0)
        model = settings.llm_model
    else:
        raise RuntimeError(f"Unknown LLM_PROVIDER: {settings.llm_provider!r}")

    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ],
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if provider == "ollama":
        kwargs["extra_body"] = {"options": {"num_ctx": settings.ollama_num_ctx}}
    try:
        resp = client.chat.completions.create(**kwargs)
    except Exception as e:
        if provider == "ollama":
            raise RuntimeError(
                f"Could not reach Ollama at {settings.ollama_base_url}. Is it running?\n"
                f"  Try:  ollama serve   (and)   ollama pull {model}"
            ) from e
        raise
    return resp.choices[0].message.content


def _extract_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found in the model response.")
    return json.loads(text[start : end + 1])


def _fit_to_context(text: str, max_output: int = 4096) -> str:
    """Truncate an over-long judgment to fit the local context window.

    Keeps the front matter and the end (ratio / final order) — what a breakdown
    needs most — and drops the long middle. Anthropic's large context is left alone.
    """
    provider = settings.llm_provider.lower()
    if provider == "anthropic":
        return text
    budget = max(1024, settings.ollama_num_ctx - max_output - 1800)  # reserve output + system
    if provider == "llamacpp":
        try:
            llm = _get_llama()
            toks = llm.tokenize(text.encode("utf-8", "ignore"), add_bos=False)
            if len(toks) <= budget:
                return text
            head = int(budget * 0.6)
            tail = budget - head - 40
            sep = llm.tokenize(b"\n\n[... lengthy middle omitted to fit the model context ...]\n\n", add_bos=False)
            return llm.detokenize(toks[:head] + sep + toks[-tail:]).decode("utf-8", "ignore")
        except Exception:
            pass
    budget_chars = int(budget * 3.5)  # ~chars/token fallback
    if len(text) <= budget_chars:
        return text
    h = int(budget_chars * 0.6)
    return text[:h] + "\n\n[... lengthy middle omitted to fit context ...]\n\n" + text[-(budget_chars - h):]


def analyze_text(case_no: str, full_text: str) -> CaseAnalysis:
    full_text = _fit_to_context(full_text, max_output=4096)
    user = (
        f"Case No: {case_no}\n\n"
        "Produce the case breakdown as ONE JSON object matching CaseAnalysis in "
        "src/schema.py. Use ONLY the judgment text below; for any field not present, "
        'use "Information not available in source text." Cite every claim as '
        "[Case No | Page:Para] using the page markers. Return ONLY the JSON.\n\n"
        f"=== JUDGMENT TEXT ===\n{full_text}"
    )
    raw = _chat(PROMPT_PATH.read_text(), user, max_tokens=4096, json_mode=True)
    return CaseAnalysis.model_validate(_extract_json(raw))


def analyze_pdf(pdf_path: str) -> CaseAnalysis:
    pages = extract_pages(pdf_path, ocr_langs=settings.tesseract_langs)
    text = "\n".join(f"===== Page {i} =====\n{t}" for i, t in enumerate(pages, 1))
    return analyze_text(case_no_from_filename(pdf_path), text)


def analyze_case(case_no: str, force: bool = False) -> CaseAnalysis:
    """On-demand + cached breakdown: analyze a judgement once, reuse thereafter."""
    from . import store

    con = store.init_db()
    if not force:
        cached = store.get_analysis(con, case_no)
        if cached:
            return CaseAnalysis.model_validate(cached)
    row = con.execute(
        "SELECT local_path FROM judgements WHERE case_no=? OR filename=? LIMIT 1",
        (case_no, case_no),
    ).fetchone()
    if not row or not row[0]:
        raise FileNotFoundError(f"No indexed judgement found for {case_no!r}")
    ca = analyze_pdf(row[0])
    model = "llamacpp-gguf" if settings.llm_provider == "llamacpp" else settings.llm_model
    store.save_analysis(con, case_no, ca.model_dump(mode="json"), f"{settings.llm_provider}:{model}")
    return ca


def precedent_test(case_x: str, scenario: str, k: int = 8) -> str:
    """3-step precedent evaluation (retrieve -> compare -> validate vs notes)."""
    from .retrieve import retrieve

    context = retrieve(f"{case_x} {scenario}", k=k)
    snippets = "\n\n".join(f"{h['meta'].get('anchor', '?')}\n{h['text']}" for h in context)
    user = (
        f"User scenario:\n{scenario}\n\nCandidate precedent: {case_x}\n\n"
        "Apply the Precedent Test (retrieve -> compare -> validate). Use ONLY the "
        "retrieved context; cite [Case No | Page:Para]; flag anything missing.\n\n"
        f"=== RETRIEVED CONTEXT ===\n{snippets}"
    )
    return _chat(PROMPT_PATH.read_text(), user, max_tokens=2048)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Break down a judgment PDF with the configured LLM.")
    ap.add_argument("pdf")
    args = ap.parse_args(argv)
    try:
        print(analyze_pdf(args.pdf).model_dump_json(indent=2))
    except RuntimeError as e:
        print(f"\n{e}\n", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
