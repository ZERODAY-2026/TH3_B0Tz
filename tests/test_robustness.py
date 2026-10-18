"""analyze()/ask() failure handling (PLAN_PS2 5.3, 9) and severity ordering (5.4)."""
import json

import pytest

from legallens.analyze import NO_ANSWER_TEXT, analyze, ask
from legallens.llm import LLMError, StubGemma
from legallens.priority import prioritise, severity, tier
from legallens.types import Document, Finding, Passage

FILLER = "The Tenant shall keep the premises clean and return them in good order. " * 45


def two_group_doc() -> Document:
    """Two long clauses -> two context groups in analyze()."""
    p1 = Passage("p1.c1", 1, "Rent", "The monthly rent shall be Rs. 15,000. " + FILLER, 0, 0)
    p2 = Passage("p2.c1", 2, "Notice", "Either party may terminate with 60 days notice. " + FILLER, 0, 0)
    return Document("d", "rental.txt", [p1, p2])


def finding(pid, quote, kind="obligation", plain=None):
    return {"kind": kind, "party": "Tenant", "label": "STATED", "confidence": "high",
            "plain_text": plain or f"The document states: {quote}", "quote": quote, "passage_id": pid}


class FailingAfter(StubGemma):
    """Answers the first n calls from the script, then behaves like a dead server."""
    def __init__(self, n, script):
        super().__init__(script=script)
        self.n = n

    def generate(self, prompt, config=None):
        if len(self.calls) >= self.n:
            self.calls.append(prompt)
            raise LLMError("local model at http://127.0.0.1:8080 failed: timed out")
        return super().generate(prompt, config)


def test_group_with_bad_json_is_skipped_and_reported():
    doc = two_group_doc()
    stub = StubGemma(script=["this is not json",
                             [finding("p2.c1", "Either party may terminate with 60 days notice.", "termination")],
                             "Either side can end it with 60 days notice [p2.c1]."])
    a = analyze(doc, client=stub)
    assert [f.passage_id for f in a.findings] == ["p2.c1"]
    assert a.coverage["incomplete"] is True and a.coverage["not_analysed"] == ["p1.c1"]
    assert any("could not be analysed" in w for w in doc.extraction_warnings)


def test_model_dying_mid_document_returns_partial_result():
    doc = two_group_doc()
    stub = FailingAfter(1, [[finding("p1.c1", "The monthly rent shall be Rs. 15,000.")]])
    a = analyze(doc, client=stub)
    assert [f.passage_id for f in a.findings] == ["p1.c1"]
    assert a.coverage["not_analysed"] == ["p2.c1"]
    assert a.summary == ""                     # summary call also hit the dead server


def test_unreachable_model_raises_clear_error():
    with pytest.raises(LLMError, match="127.0.0.1"):
        analyze(two_group_doc(), client=FailingAfter(0, []))


@pytest.mark.parametrize("payload", ["not json at all", "[]", json.dumps({"citations": [{"bad": 1}]})])
def test_ask_handles_malformed_answers(payload):
    doc = two_group_doc()
    r = ask(doc, "What is the notice period?", client=StubGemma(script=[payload]))
    if payload.startswith("{"):                # a dict with junk citations: kept text, no citations
        assert r.citations == []
    else:
        assert r.text == NO_ANSWER_TEXT and not r.silent and not r.refused


def test_ask_propagates_dead_server():
    with pytest.raises(LLMError):
        ask(two_group_doc(), "What is the notice period?", client=FailingAfter(0, []))


# ------------------------------------------------------------------ priority

def F(kind, label="STATED", confidence="high", flags=None):
    return Finding(id=kind, kind=kind, party=None, plain_text="x", quote="x", passage_id="p1.c1",
                   label=label, confidence=confidence, flags=flags or [])


def test_severity_matches_plan_formula():
    assert severity(F("penalty")) == 5.0
    assert severity(F("ambiguity", "CONCERN", "medium")) == pytest.approx(2 * 0.7 * 0.9)
    assert severity(F("something_new", "ODD", "unknown")) == pytest.approx(1 * 0.4 * 0.8)


def test_tiers():
    assert tier(F("penalty")) == "critical"
    assert tier(F("obligation")) == "important"
    assert tier(F("right")) == "informational"


def test_prioritise_orders_by_severity_and_sinks_unverified():
    items = [F("right"), F("penalty", flags=["unverified"]), F("obligation"), F("termination")]
    assert [f.kind for f in prioritise(items)] == ["termination", "obligation", "right", "penalty"]


def test_analyze_returns_findings_most_severe_first():
    p = Passage("p1.c1", 1, "Rent", "The Tenant shall pay rent of Rs. 15,000. A late fee of Rs. 500 per day applies.", 0, 0)
    doc = Document("d", "rental.txt", [p])
    stub = StubGemma(script=[[finding("p1.c1", "The Tenant shall pay rent of Rs. 15,000."),
                              finding("p1.c1", "A late fee of Rs. 500 per day applies.", "penalty")],
                             "Rent is Rs. 15,000 [p1.c1]."])
    a = analyze(doc, client=stub)
    assert [f.kind for f in a.findings] == ["penalty", "obligation"]
