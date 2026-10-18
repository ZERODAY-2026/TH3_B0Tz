"""Prompt-injection defence for LegalLens (Person C, H8-H9).

Document text is untrusted data, never instructions (PLAN_PS2 section 6.4).
This module is a pre-scan only: it flags instruction-like strings inside a
document so the user is warned, and the fixed JSON schema + the stub
responses that decline on unmatched prompts (legallens.llm.StubGemma) are
what actually stop an injected instruction from changing the model's output
shape. Nothing here calls the model.
"""
from __future__ import annotations

import re

from .types import Document

INJECTION_PATTERNS = (
    r"ignore\s+(all\s+)?(the\s+)?previous\s+instructions",
    r"ignore\s+(all\s+)?prior\s+instructions",
    r"you\s+are\s+now\s+(a|an)\b",
    r"disregard\s+(the|all)\s+(above|previous)",
    r"output\s+the\s+following",
    r"new\s+instructions\s*:",
    r"system\s+prompt",
    r"act\s+as\s+(a|an)\b",
    r"pretend\s+you\s+are",
    r"this\s+contract\s+is\s+fully\s+legal\s+and\s+safe\s+to\s+sign",
)

_COMPILED = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]

WARNING_TEXT = (
    "this document contains text that looks like an instruction to an AI; "
    "it was ignored"
)


def scan(text: str) -> list[str]:
    """Return the matched snippets (lowercased pattern source, not the raw
    text, to avoid echoing attacker-controlled strings verbatim back into
    logs/UI).
    """
    hits: list[str] = []
    for pattern, compiled in zip(INJECTION_PATTERNS, _COMPILED):
        if compiled.search(text):
            hits.append(pattern)
    return hits


def scan_document(doc: Document) -> list[str]:
    """Scan every passage; one warning for the whole document if anything
    matched (PLAN section 6.4 exact wording), else an empty list.
    """
    for passage in doc.passages:
        if scan(passage.text):
            return [WARNING_TEXT]
    return []
