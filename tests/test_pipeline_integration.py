"""Integration: analyze.py's lazy-import wiring picks up the now-landed
verify.py, safety.py and injection.py (PLAN_PS2 checkpoints H6/H9). Confirms
the "swap is automatic, no pipeline changes" promise in docs/API.md holds.
"""
import json

from legallens.analyze import analyze
from legallens.llm import StubGemma

from .samples import INJECTED, RENTAL, VAGUE


def test_analyze_injected_doc_surfaces_warning_on_document():
    client = StubGemma(responses={
        "you read legal document passages": json.dumps([
            {"kind": "obligation", "party": "Tenant",
             "plain_text": "The document states rent of Rs. 12,000 is payable in advance.",
             "quote": "The monthly rent shall be Rs. 12,000, payable in advance.",
             "passage_id": "p1.c1", "label": "STATED", "confidence": "high"},
        ]),
        "brief summary": "Rent of Rs. 12,000 is payable in advance [p1.c1].",
    })
    analyze(INJECTED, client=client)
    assert any("instruction" in w for w in INJECTED.extraction_warnings)


def test_analyze_clean_doc_no_injection_warning():
    client = StubGemma(responses={
        "you read legal document passages": json.dumps([
            {"kind": "obligation", "party": "Tenant",
             "plain_text": "The document states rent of Rs. 15,000 is due monthly.",
             "quote": "The monthly rent shall be Rs. 15,000 (Rupees Fifteen Thousand only), "
                      "payable on or before the 5th of each month.",
             "passage_id": "p1.c1", "label": "STATED", "confidence": "high"},
        ]),
        "brief summary": "Rent of Rs. 15,000 is due monthly [p1.c1].",
    })
    analyze(RENTAL, client=client)
    assert RENTAL.extraction_warnings == []


def test_analyze_findings_no_longer_flagged_unverified_stub():
    # Once verify.py lands, the permissive stub path in analyze.py is no
    # longer used -- real verification runs instead.
    client = StubGemma(responses={
        "you read legal document passages": json.dumps([
            {"kind": "obligation", "party": "Tenant",
             "plain_text": "The document states rent of Rs. 15,000 is due monthly.",
             "quote": "The monthly rent shall be Rs. 15,000 (Rupees Fifteen Thousand only), "
                      "payable on or before the 5th of each month.",
             "passage_id": "p1.c1", "label": "STATED", "confidence": "high"},
        ]),
        "brief summary": "Rent of Rs. 15,000 is due monthly [p1.c1].",
    })
    a = analyze(RENTAL, client=client)
    assert all("unverified_stub" not in f.flags for f in a.findings)


def test_analyze_vague_doc_findings_get_ambiguity_flag():
    client = StubGemma(responses={
        "you read legal document passages": json.dumps([
            {"kind": "obligation", "party": "Landlord",
             "plain_text": "The document states the landlord may carry out repairs at "
                           "its discretion within a reasonable time.",
             "quote": "The Landlord may carry out repairs at its sole discretion and "
                      "within a reasonable time.",
             "passage_id": "p1.c1", "label": "STATED", "confidence": "high"},
        ]),
        "brief summary": "The landlord may carry out repairs at its discretion [p1.c1].",
    })
    a = analyze(VAGUE, client=client)
    assert any("ambiguous" in f.flags for f in a.findings)
