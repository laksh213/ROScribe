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

    @field_validator("case_no", "date", "parties", "court_division", mode="before")
    @classmethod
    def _str_from_list(cls, v):
        if isinstance(v, list):
            return " ".join(str(x) for x in v if x) or NOT_AVAILABLE
        return v

    @field_validator("judges", "jurisdiction_tags", "keywords", mode="before")
    @classmethod
    def _list_from_str(cls, v):
        if isinstance(v, str):
            return [v] if v.strip() else []
        return v


class LegalIssue(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    question: str = Field(validation_alias=AliasChoices("question", "issue", "legal_issue", "text"))
    citation: Citation | None = None


class EvidenceItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    description: str = Field(validation_alias=AliasChoices("description", "evidence", "item", "text"))
    evidentiary_value: str = NOT_AVAILABLE
    citation: Citation | None = None


class PrecedentReference(BaseModel):
    # Tolerate the field-name variants small models emit.
    model_config = ConfigDict(populate_by_name=True)

    cited_case: str = Field(
        validation_alias=AliasChoices("cited_case", "case_name", "case", "name", "title")
    )
    treatment: PrecedentTreatment = Field(
        default=PrecedentTreatment.NOT_AVAILABLE,
        validation_alias=AliasChoices("treatment", "precedence", "precedent_treatment", "status"),
    )
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

    # --- tolerance for LLM output variance (esp. small local models) ---
    @field_validator(
        "factual_matrix", "ratio_decidendi", "final_order", "academic_synthesis", mode="before"
    )
    @classmethod
    def _coerce_str(cls, v):
        if isinstance(v, list):
            return " ".join(str(x) for x in v if x is not None)
        if isinstance(v, dict):
            return " ".join(f"{k}: {x}" for k, x in v.items())
        return v

    @field_validator(
        "topics_discussed", "deciding_factors", "legislation_cited", "conflicts_flagged", mode="before"
    )
    @classmethod
    def _coerce_list(cls, v):
        if isinstance(v, str):
            return [v] if v.strip() else []
        return v

    @field_validator("legal_issues", mode="before")
    @classmethod
    def _wrap_issues(cls, v):
        if isinstance(v, str):
            v = [v] if v.strip() else []
        if isinstance(v, list):
            return [{"question": x} if isinstance(x, str) else x for x in v]
        return v

    @field_validator("evidence_weighing", mode="before")
    @classmethod
    def _wrap_evidence(cls, v):
        if isinstance(v, str):
            v = [v] if v.strip() else []
        if isinstance(v, list):
            return [{"description": x} if isinstance(x, str) else x for x in v]
        return v

    @field_validator("precedent_index", mode="before")
    @classmethod
    def _wrap_precedents(cls, v):
        if isinstance(v, list):
            return [{"cited_case": x} if isinstance(x, str) else x for x in v]
        return v

    # --- quality gate ("zap check") -------------------------------------- #
    # The substantive fields a real judgment breakdown must populate. NOT_AVAILABLE
    # is the *correct* value for a field genuinely absent from the source, but a
    # breakdown where almost ALL of these are empty means extraction failed (the
    # model never digested the text — context overflow, bad JSON, etc.), not that
    # a 14-page judgment truly lacks facts, a ratio, and an order.
    _CORE_FIELDS = (
        "factual_matrix", "ratio_decidendi", "final_order",
        "legal_issues", "deciding_factors", "topics_discussed", "precedent_index",
    )

    @staticmethod
    def _is_filled(value) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip()) and value.strip() != NOT_AVAILABLE
        if isinstance(value, (list, tuple)):
            return any(CaseAnalysis._is_filled(x) for x in value)
        if isinstance(value, LegalIssue):
            return CaseAnalysis._is_filled(value.question)
        if isinstance(value, EvidenceItem):
            return CaseAnalysis._is_filled(value.description)
        if isinstance(value, PrecedentReference):
            return CaseAnalysis._is_filled(value.cited_case)
        return True

    def filled_core_count(self) -> int:
        """How many of the core narrative fields carry real, non-placeholder content."""
        return sum(1 for f in self._CORE_FIELDS if self._is_filled(getattr(self, f)))

    def quality(self) -> dict:
        """A cheap completeness signal for the UI / verifier / caching gate.

        Returns ``{filled, total, ratio, hollow}``. ``hollow`` is True when the
        breakdown is essentially empty (fewer than 2 core fields populated) —
        the signal that the extraction failed and should be retried, not cached."""
        filled = self.filled_core_count()
        total = len(self._CORE_FIELDS)
        return {
            "filled": filled,
            "total": total,
            "ratio": round(filled / total, 2),
            "hollow": filled < 2,
        }
