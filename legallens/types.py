"""H0-agreed shared types for LegalLens (PLAN_PS2 section 5.1).

Field names match the plan exactly. Changing anything here needs all four
people's agreement (cross-lane rule, section 8).
"""
from __future__ import annotations

from dataclasses import dataclass, field

KINDS = ("obligation", "right", "deadline", "penalty", "termination",
         "ambiguity", "risk")
LABELS = ("STATED", "INTERPRETATION", "CONCERN")
CONFIDENCE = ("high", "medium", "low")


@dataclass
class Passage:
    id: str                 # e.g. "p3.c2" (page 3, clause 2) - stable, human-readable
    page: int
    heading: str | None
    text: str
    start: int              # character offsets in the extracted document text
    end: int


@dataclass
class Document:
    doc_id: str
    source_name: str
    passages: list[Passage]
    extraction_warnings: list[str] = field(default_factory=list)

    def passage(self, passage_id: str) -> Passage | None:
        for p in self.passages:
            if p.id == passage_id:
                return p
        return None


@dataclass
class Finding:
    id: str
    kind: str               # one of KINDS
    party: str | None       # who it applies to, as written in the document
    plain_text: str         # plain-language explanation
    quote: str              # verbatim text from the document
    passage_id: str
    label: str              # one of LABELS
    confidence: str = "medium"
    flags: list[str] = field(default_factory=list)  # ambiguous, quote_corrected, unverified, ...
    escalation_note: str | None = None


@dataclass
class Analysis:
    summary: str
    summary_citations: list[str]   # passage IDs backing the summary (6.1.6)
    findings: list[Finding]
    coverage: dict                 # which clause types were/weren't found


@dataclass
class Citation:
    passage_id: str
    quote: str


@dataclass
class Reply:
    text: str
    citations: list[Citation] = field(default_factory=list)
    silent: bool = False
    refused: bool = False
    escalation_note: str | None = None


@dataclass
class VerifyResult:
    ok: bool
    reason: str = ""
    repaired_quote: str | None = None
    pruned_summary: str | None = None


@dataclass
class SafeOutput:
    """Return type of safety.apply_safety() (PLAN_PS2 section 5.2). Additive
    to the H0 contract -- apply_safety() was always named in the plan but
    never given a concrete return type until lane C landed."""
    item: "Analysis | Reply"
    disclaimer: str
    blocked_phrases: list[str] = field(default_factory=list)
