"""Checkpoint 1 (PLAN_PS2 H4): the verifier rejects 3 fabricated quotes and
3 distorted numbers, and passes 3 real ones. Plus Reply and Analysis
verification, and near-match repair.
"""
from legallens.types import Analysis, Citation, Finding, Reply
from legallens.verify import verify

from .samples import RENTAL

# --------------------------------------------------------- real quotes (3)

def _real_finding(passage_id: str, quote: str, plain_text: str) -> Finding:
    return Finding(id="x", kind="obligation", party=None, plain_text=plain_text,
                   quote=quote, passage_id=passage_id, label="STATED")


def test_real_quote_rent_passes():
    f = _real_finding(
        "p1.c1",
        "The monthly rent shall be Rs. 15,000 (Rupees Fifteen Thousand only), "
        "payable on or before the 5th of each month.",
        "The document states rent of Rs. 15,000 is due by the 5th of each month.",
    )
    r = verify(f, RENTAL)
    assert r.ok is True


def test_real_quote_penalty_passes():
    f = _real_finding(
        "p2.c1",
        "the Tenant shall pay a late fee of Rs. 500 per day",
        "The document states a late fee of Rs. 500 per day applies.",
    )
    r = verify(f, RENTAL)
    assert r.ok is True


def test_real_quote_termination_passes():
    f = _real_finding(
        "p2.c2",
        "Either party may terminate this agreement by giving 60 days written "
        "notice to the other party.",
        "The document states either party may terminate with 60 days notice.",
    )
    r = verify(f, RENTAL)
    assert r.ok is True


# ---------------------------------------------------- fabricated quotes (3)

def test_fabricated_quote_wrong_passage_rejected():
    f = _real_finding("p1.c2", "The deposit is refundable within 10 days of move-out.",
                       "The document states the deposit is refundable in 10 days.")
    r = verify(f, RENTAL)
    assert r.ok is False and r.repaired_quote is None


def test_fabricated_quote_invented_clause_rejected():
    f = _real_finding("p2.c2", "The Tenant may sublet the premises without consent.",
                       "The document allows subletting without consent.")
    r = verify(f, RENTAL)
    assert r.ok is False and r.repaired_quote is None


def test_fabricated_quote_unrelated_text_rejected():
    f = _real_finding("p3.c1", "Pets are strictly prohibited on the premises.",
                       "The document states pets are not allowed.")
    r = verify(f, RENTAL)
    assert r.ok is False and r.repaired_quote is None


# ----------------------------------------------------- distorted numbers (3)

def test_distorted_number_days_to_months_rejected():
    f = _real_finding(
        "p2.c2",
        "Either party may terminate this agreement by giving 60 days written "
        "notice to the other party.",
        "The document states either party may terminate with 2 months notice.",
    )
    r = verify(f, RENTAL)
    assert r.ok is False
    assert "unverified" not in f.flags  # analyze.py adds the flag, not verify()


def test_distorted_amount_rejected():
    f = _real_finding(
        "p1.c2",
        "The Tenant shall pay a security deposit of Rs. 45,000 (Rupees "
        "Forty-Five Thousand only) at the time of signing this agreement.",
        "The document states a security deposit of Rs. 90,000.",
    )
    r = verify(f, RENTAL)
    assert r.ok is False


def test_distorted_penalty_rate_rejected():
    f = _real_finding(
        "p2.c1",
        "If rent is not paid within 5 days of the due date, the Tenant shall "
        "pay a late fee of Rs. 500 per day until payment is received.",
        "The document states a late fee of Rs. 5,000 per day applies.",
    )
    r = verify(f, RENTAL)
    assert r.ok is False


# ------------------------------------------------------------ near-match

def test_near_match_dropped_comma_is_repaired():
    f = _real_finding(
        "p1.c2",
        "The Tenant shall pay a security deposit of Rs. 45000 (Rupees "
        "Forty-Five Thousand only) at the time of signing this agreement.",
        "The document states a security deposit of Rs. 45,000.",
    )
    r = verify(f, RENTAL)
    assert r.ok is False
    assert r.repaired_quote is not None
    assert "45,000" in r.repaired_quote or "45000" in r.repaired_quote


def test_missing_passage_rejected():
    f = _real_finding("p9.c9", "anything", "anything")
    r = verify(f, RENTAL)
    assert r.ok is False and "not found" in r.reason


# --------------------------------------------------------------------- reply

def test_reply_grounded_citation_passes():
    r = Reply(
        text="The document states a late fee of Rs. 500 per day applies.",
        citations=[Citation(passage_id="p2.c1",
                             quote="the Tenant shall pay a late fee of Rs. 500 per day")],
    )
    result = verify(r, RENTAL)
    assert result.ok is True


def test_reply_fabricated_citation_fails():
    r = Reply(
        text="The deposit is Rs. 90,000.",
        citations=[Citation(passage_id="p1.c2", quote="security deposit of Rs. 90,000")],
    )
    result = verify(r, RENTAL)
    assert result.ok is False


def test_reply_no_citations_non_silent_fails():
    r = Reply(text="The deposit is Rs. 90,000.", citations=[], silent=False, refused=False)
    result = verify(r, RENTAL)
    assert result.ok is False


def test_reply_silent_trivially_ok():
    r = Reply(text="The document does not appear to say anything about this.",
              citations=[], silent=True)
    assert verify(r, RENTAL).ok is True


def test_reply_refused_no_citations_ok():
    r = Reply(text="I cannot determine that.", citations=[], refused=True)
    assert verify(r, RENTAL).ok is True


# ------------------------------------------------------------------ analysis

def test_summary_sentence_without_citation_dropped():
    a = Analysis(
        summary=("Rent is Rs. 15,000 per month [p1.c1]. "
                  "The tenant may sublet freely without landlord consent."),
        summary_citations=["p1.c1"],
        findings=[],
        coverage={},
    )
    result = verify(a, RENTAL)
    assert result.ok is False
    assert "sublet" not in result.pruned_summary
    assert "15,000" in result.pruned_summary


def test_summary_sentence_number_mismatch_dropped():
    a = Analysis(
        summary=("The late fee is Rs. 5,000 per day [p2.c1]. "
                  "Either party may terminate with 60 days notice [p2.c2]."),
        summary_citations=["p2.c1", "p2.c2"],
        findings=[],
        coverage={},
    )
    result = verify(a, RENTAL)
    assert result.ok is False
    assert "5,000" not in result.pruned_summary
    assert "60 days" in result.pruned_summary


def test_summary_all_sentences_pass():
    a = Analysis(
        summary=("Rent is Rs. 15,000 per month [p1.c1]. "
                  "A late fee of Rs. 500 per day applies after 5 days [p2.c1]."),
        summary_citations=["p1.c1", "p2.c1"],
        findings=[],
        coverage={},
    )
    result = verify(a, RENTAL)
    assert result.ok is True
    assert result.pruned_summary == a.summary


def test_verify_unsupported_type_raises():
    import pytest
    with pytest.raises(TypeError):
        verify("not a Finding/Reply/Analysis", RENTAL)
