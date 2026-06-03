"""Phase 5 — Grounded analysis & structured breakdown.

Calls Claude (`prompts/system_prompt.md`) over ONLY the retrieved chunks to
produce a validated `CaseAnalysis` (src/schema.py): topics, facts, deciding
factors, evidence, case law cited, legislation, ratio, final order, and an
academic synthesis against the personal repository. Enforces source-fidelity and
`[Case No | Page:Para]` citations.

TODO (Phase 5): implement analyze_case + the precedent_test workflow.
"""

from __future__ import annotations

from .retrieve import retrieve  # noqa: F401  (used once implemented)
from .schema import CaseAnalysis


def analyze_case(case_no: str) -> CaseAnalysis:
    """Retrieve the case's chunks, prompt Claude, validate the JSON breakdown."""
    raise NotImplementedError("Phase 5: retrieve -> prompt Claude -> validate.")


def precedent_test(case_x: str, scenario: str) -> str:
    """3-step precedent evaluation: retrieve -> compare -> validate vs notes."""
    raise NotImplementedError("Phase 5: implement the precedent test workflow.")
