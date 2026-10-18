"""UI pipeline seam — Person D.

Wraps the real legallens pipeline (A/B/C's merged code). The UI consumes
only the H0 dataclasses from legallens/types.py, plus two view-model fields
carried on Document (source_name, extraction_warnings) that the UI surfaces
directly. If the pipeline import fails (early stub wiring), a clear error is
raised — there is no silent stub mode any more: the real code is on main.
"""

from __future__ import annotations

from legallens.analyze import analyze, ask
from legallens.ingest import ingest
from legallens.types import Document, Reply

DISCLAIMER = (
    "LegalLens gives preliminary, document-based explanations only. It is not legal advice "
    "and does not assess whether any clause is valid or enforceable. Consult a qualified "
    "lawyer for advice on your situation."
)

SILENT_TEXT = (
    "The document does not appear to say anything about this. Consider asking the other "
    "party to clarify in writing, or discussing it with a lawyer."
)

# --- severity scoring (PLAN §5.4) — same weights C uses in priority -------

KIND_WEIGHT = {
    "penalty": 5, "termination": 5, "deadline": 4, "obligation": 3,
    "risk": 3, "concern": 3, "ambiguity": 2, "right": 1,
}
CONFIDENCE_WEIGHT = {"high": 1.0, "medium": 0.7, "low": 0.4}
LABEL_BOOST = {"STATED": 1.0, "INTERPRETATION": 0.8, "CONCERN": 0.9}


def severity(f) -> float:
    return (
        KIND_WEIGHT.get(f.kind, 1)
        * CONFIDENCE_WEIGHT.get(f.confidence, 0.5)
        * LABEL_BOOST.get(f.label, 0.8)
    )


def tiers(findings):
    """Group findings into the three display tiers (PLAN §5.4)."""
    out: dict[str, list] = {"Critical": [], "Important": [], "Informational": []}
    for f in sorted(findings, key=severity, reverse=True):
        s = severity(f)
        tier = "Critical" if s >= 4 else "Important" if s >= 2 else "Informational"
        out[tier].append(f)
    return out


# --- pipeline access --------------------------------------------------------

def get_analysis(path: str):
    """ingest + analyze; returns (Document, Analysis) so the UI can show
    extraction warnings and the source name from the Document."""
    doc = ingest(path)
    return doc, analyze(doc)


def get_reply(doc: Document, question: str) -> Reply:
    return ask(doc, question)
