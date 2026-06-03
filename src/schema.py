"""Pydantic models for the ROScribe unified case-breakdown schema.

Every judgment is normalised into a `CaseAnalysis`. This is the single contract
shared by the extraction prompt (`prompts/system_prompt.md`), the retrieval
layer, and the UI. The fields map directly to the breakdown facets requested:
topics discussed, facts, deciding factors, evidence, case law cited, legislation,
and final judgement.

Rule (CLAUDE.md > Operational Guidelines): when a field cannot be grounded in the
source PDF, use `NOT_AVAILABLE` rather than guessing.
"""

from __future__ import annotations

from enum import Enum

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

NOT_AVAILABLE = "Information not available in source text."


class PrecedentTreatment(str, Enum):
    APPLIED = "Applied"
    FOLLOWED = "Followed"
    DISTINGUISHED = "Distinguished"
    OVERRULED = "Overruled"
    CONSIDERED = "Considered"
    NOT_AVAILABLE = NOT_AVAILABLE


class Citation(BaseModel):
    """A verifiable pin-cite. Renders as `[Case No | Page:Para]`."""

    case_no: str
    page: int | None = None
    para: str | None = None

    def render(self) -> str:
        page = self.page if self.page is not None else "?"
        para = self.para if self.para is not None else "?"
        return f"[{self.case_no} | {page}:{para}]"

    def __str__(self) -> str:
        return self.render()


class Metadata(BaseModel):
    case_no: str = NOT_AVAILABLE
    date: str = NOT_AVAILABLE
    judges: list[str] = Field(default_factory=list)
    parties: str = NOT_AVAILABLE
    court_division: str = NOT_AVAILABLE
    jurisdiction_tags: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)  # seeded from the archive table


class LegalIssue(BaseModel):
    question: str
    citation: Citation | None = None


class EvidenceItem(BaseModel):
    description: str
    evidentiary_value: str = NOT_AVAILABLE
    citation: Citation | None = None


class PrecedentReference(BaseModel):
    cited_case: str
    treatment: PrecedentTreatment = PrecedentTreatment.NOT_AVAILABLE
    note: str = ""
    citation: Citation | None = None


class CaseAnalysis(BaseModel):
    """Top-level unified breakdown for one judgment."""

    metadata: Metadata = Field(default_factory=Metadata)
    topics_discussed: list[str] = Field(default_factory=list)
    factual_matrix: str = NOT_AVAILABLE                     # the facts
    legal_issues: list[LegalIssue] = Field(default_factory=list)
    evidence_weighing: list[EvidenceItem] = Field(default_factory=list)  # evidence
    precedent_index: list[PrecedentReference] = Field(default_factory=list)  # case law cited
    legislation_cited: list[str] = Field(default_factory=list)  # statutes / acts
    deciding_factors: list[str] = Field(default_factory=list)   # key factors driving the outcome
    ratio_decidendi: str = NOT_AVAILABLE                    # binding reasoning
    final_order: str = NOT_AVAILABLE                        # final judgement
    academic_synthesis: str = NOT_AVAILABLE                 # analysis vs personal repository
    # Populated by the synthesis step when the court diverges from the notes.
    conflicts_flagged: list[str] = Field(default_factory=list)
