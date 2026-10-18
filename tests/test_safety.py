"""Tests for legallens.safety: classify_question, refusal_reply, label
downgrade, ambiguity/jurisdiction flags, forbidden-phrase filter, and
apply_safety (PLAN_PS2 section 6.2-6.3, H3-H9).
"""
from legallens.safety import (
    DISCLAIMER,
    FORBIDDEN_PHRASES,
    apply_safety,
    classify_question,
    detect_conflicts,
    downgrade_label,
    filter_forbidden_phrases,
    flag_ambiguity,
    flag_jurisdiction,
    refusal_reply,
)
from legallens.types import Analysis, Finding, Reply

# ------------------------------------------------------------ classification

def test_classify_verdict_is_this_enforceable():
    assert classify_question("Is this enforceable?") == "verdict_request"


def test_classify_verdict_should_i_sign():
    assert classify_question("Should I sign this?") == "verdict_request"


def test_classify_verdict_can_they_do_this():
    assert classify_question("Can they do this to me?") == "verdict_request"


def test_classify_verdict_is_this_legal():
    assert classify_question("Is this legal in my state?") == "verdict_request"


def test_classify_off_topic_write_poem():
    assert classify_question("Write me a poem about spring") == "off_topic"


def test_classify_off_topic_who_are_you():
    assert classify_question("Who are you?") == "off_topic"


def test_classify_document_question_general_knowledge_not_forced_refusal():
    # Must NOT be verdict_request or off_topic -- analyze.py relies on this
    # falling through to retrieval + the silent path (test_analyze.py pins it).
    assert classify_question("What is the capital of France?") == "document_question"


def test_classify_document_question_normal_query():
    assert classify_question("What is the late fee?") == "document_question"


# ----------------------------------------------------------------- refusal

def test_refusal_verdict_mentions_lawyer_and_topic():
    r = refusal_reply("Is this enforceable?", "verdict_request")
    assert r.refused is True
    assert "qualified legal professional" in r.text.lower()
    assert r.citations == []
    assert r.escalation_note is not None


def test_refusal_off_topic_no_legal_escalation_framing():
    r = refusal_reply("Write me a poem", "off_topic")
    assert r.refused is True
    assert "qualified legal professional" not in r.text.lower()


def test_refusal_specific_not_generic_topic_extraction():
    r = refusal_reply("Is the non-compete clause enforceable?", "verdict_request")
    assert "non compete" in r.text.lower() or "noncompete" in r.text.lower() or \
           "non-compete" in r.text.lower() or "compete" in r.text.lower()


# ---------------------------------------------------------- label downgrade

def _finding(label="STATED", quote="", plain_text=""):
    return Finding(id="x", kind="obligation", party=None, plain_text=plain_text,
                   quote=quote, passage_id="p1.c1", label=label)


def test_downgrade_label_when_plain_text_adds_unsupported_fact():
    f = _finding(
        quote="The Tenant shall pay a security deposit of Rs. 45,000.",
        plain_text="This means the landlord can evict the tenant immediately "
                   "without any court process if rent is late.",
    )
    downgrade_label(f)
    assert f.label == "INTERPRETATION"
    assert "label_downgraded" in f.flags


def test_no_downgrade_when_plain_text_closely_tracks_quote():
    f = _finding(
        quote="The Tenant shall pay a security deposit of Rs. 45,000.",
        plain_text="The document states the tenant must pay a security "
                   "deposit of Rs. 45,000.",
    )
    downgrade_label(f)
    assert f.label == "STATED"


def test_downgrade_only_applies_to_stated():
    f = _finding(label="CONCERN", quote="x", plain_text="totally unrelated text here")
    downgrade_label(f)
    assert f.label == "CONCERN"


# --------------------------------------------------------------- ambiguity

def test_flag_ambiguity_vague_term():
    f = _finding(quote="The Landlord may act at its sole discretion regarding repairs.")
    flags = flag_ambiguity(f)
    assert "ambiguous" in flags


def test_flag_ambiguity_blank_placeholder():
    f = _finding(quote="The notice period shall be ___ days.")
    flags = flag_ambiguity(f)
    assert "ambiguous" in flags


def test_flag_ambiguity_clear_clause_not_flagged():
    f = _finding(quote="The monthly rent shall be Rs. 15,000.")
    flags = flag_ambiguity(f)
    assert "ambiguous" not in flags


# ------------------------------------------------------------- jurisdiction

def test_flag_jurisdiction_security_deposit():
    f = _finding(quote="The Tenant shall pay a security deposit of Rs. 45,000.")
    flags = flag_jurisdiction(f)
    assert "jurisdiction_dependent" in flags
    assert f.escalation_note is not None


def test_flag_jurisdiction_non_compete():
    f = _finding(quote="The Employee agrees to a non-compete clause for 1 year.")
    flags = flag_jurisdiction(f)
    assert "jurisdiction_dependent" in flags


def test_flag_jurisdiction_unrelated_not_flagged():
    f = _finding(quote="The parties shall communicate by email.")
    flags = flag_jurisdiction(f)
    assert "jurisdiction_dependent" not in flags


# ------------------------------------------------------- forbidden phrases

def test_forbidden_phrase_each_listed_phrase_caught():
    for phrase in FORBIDDEN_PHRASES:
        text = f"This clause {phrase} according to our analysis."
        cleaned, hits = filter_forbidden_phrases(text)
        assert hits, f"{phrase!r} was not caught"
        assert phrase.lower() not in cleaned.lower()


def test_forbidden_phrase_clean_text_untouched():
    text = "The document states rent of Rs. 15,000 is due monthly."
    cleaned, hits = filter_forbidden_phrases(text)
    assert cleaned == text
    assert hits == []


# --------------------------------------------------------------- apply_safety

def test_apply_safety_analysis_attaches_disclaimer_and_scrubs():
    a = Analysis(
        summary="This clause is clearly illegal and should not sign.",
        summary_citations=[],
        findings=[_finding(quote="x", plain_text="y")],
        coverage={},
    )
    out = apply_safety(a, doc=None)
    assert out.disclaimer == DISCLAIMER
    assert "illegal" not in out.item.summary.lower()
    assert out.blocked_phrases


def test_apply_safety_reply_scrubs_forbidden_phrase():
    r = Reply(text="This is void and unenforceable.")
    out = apply_safety(r, doc=None)
    assert "void" not in out.item.text.lower()
    assert out.disclaimer == DISCLAIMER


def test_apply_safety_unsupported_type_raises():
    import pytest
    with pytest.raises(TypeError):
        apply_safety("not analysis or reply", doc=None)


# --------------------------------------------------------------- conflicts

def test_detect_conflicts_contradictory_notice_periods():
    f1 = Finding(id="a", kind="termination", party="Either party",
                 plain_text="30 days notice required",
                 quote="Either party may terminate this agreement by giving 30 days "
                       "written notice.",
                 passage_id="p1.c1", label="STATED")
    f2 = Finding(id="b", kind="termination", party="Employee",
                 plain_text="90 days notice required",
                 quote="Notwithstanding the above, the Employee shall give 90 days "
                       "written notice before resignation.",
                 passage_id="p3.c4", label="STATED")
    flagged = detect_conflicts([f1, f2])
    assert flagged
    assert "conflicting" in f1.flags and "conflicting" in f2.flags


def test_detect_conflicts_no_conflict_when_consistent():
    f1 = Finding(id="a", kind="termination", party=None,
                 plain_text="60 days notice", quote="60 days written notice",
                 passage_id="p1.c1", label="STATED")
    f2 = Finding(id="b", kind="penalty", party=None,
                 plain_text="Rs. 500 fee", quote="late fee of Rs. 500 per day",
                 passage_id="p2.c1", label="STATED")
    flagged = detect_conflicts([f1, f2])
    assert flagged == []
    assert "conflicting" not in f1.flags


# ------------------------------------------------- review fixes (wording)

def test_forbidden_filter_leaves_factual_validity_and_legal_words():
    for text in (
        "This agreement is valid for 11 months from the start date.",
        "The deposit is legally refundable within 30 days.",
        "Rent is legal tender payable monthly.",
        "The Tenant shall serve a legal notice before vacating.",
    ):
        cleaned, hits = filter_forbidden_phrases(text)
        assert hits == [] and cleaned == text, text


def test_forbidden_filter_still_catches_verdicts():
    for text in ("This clause is unenforceable.", "This penalty is valid.",
                 "You should not sign this agreement.", "The non-compete is void."):
        cleaned, hits = filter_forbidden_phrases(text)
        assert hits, text
        assert "[redacted]" in cleaned


def test_classify_legal_as_adjective_is_a_document_question():
    for q in ("What is the legal notice period?",
              "Does the agreement mention legal fees?",
              "What is the late fee?"):
        assert classify_question(q) == "document_question", q


def test_classify_more_verdict_framings():
    for q in ("Is the late fee legal?", "Will this hold up in court?",
              "Is this non-compete valid in India?", "Should I accept this offer?",
              "Can I sue my landlord over this?"):
        assert classify_question(q) == "verdict_request", q
