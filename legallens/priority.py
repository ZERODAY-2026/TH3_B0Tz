"""Finding severity and ordering (PLAN_PS2 section 5.4).

Severity is computed by code, never by the model, so the order the user sees
is deterministic and explainable. Findings that failed verification always
sort last, whatever their score, because the UI hides them by default.
"""
from __future__ import annotations

from .types import Finding

KIND_WEIGHT = {
    "penalty": 5, "termination": 5, "deadline": 4, "obligation": 3,
    "risk": 3, "concern": 3, "ambiguity": 2, "right": 1,
}
CONFIDENCE_WEIGHT = {"high": 1.0, "medium": 0.7, "low": 0.4}
LABEL_BOOST = {"STATED": 1.0, "INTERPRETATION": 0.8, "CONCERN": 0.9}

TIERS = (("critical", 4.0), ("important", 2.0), ("informational", 0.0))


def severity(f: Finding) -> float:
    """KIND_WEIGHT x CONFIDENCE_WEIGHT x LABEL_BOOST; unknown values count low."""
    return round(KIND_WEIGHT.get(f.kind, 1)
                 * CONFIDENCE_WEIGHT.get(f.confidence, 0.4)
                 * LABEL_BOOST.get(f.label, 0.8), 3)


def tier(f: Finding) -> str:
    """"critical" (>= 4), "important" (2 to 3.99) or "informational" (< 2)."""
    s = severity(f)
    return next(name for name, floor in TIERS if s >= floor)


def prioritise(findings: list[Finding]) -> list[Finding]:
    """Most severe first; verified before unverified; ties keep document order."""
    return sorted(findings, key=lambda f: ("unverified" in f.flags, -severity(f)))
