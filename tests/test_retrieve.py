"""Lane B: hybrid retrieval (BM25 + MiniLM/FAISS) and its wiring into ask()."""
import json
from pathlib import Path

import pytest

from legallens import retrieve as R
from legallens.analyze import ask
from legallens.ingest import ingest
from legallens.llm import StubGemma
from legallens.types import Document

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples"
RENTAL = ingest(SAMPLES / "rental_clear.pdf")
EMPLOYMENT = ingest(SAMPLES / "employment_standard.txt")

# (document, question, text that identifies the right clause)
CASES = [
    (RENTAL, "What is the notice period?", "6.1"),
    (RENTAL, "Can I leave the flat early?", "6.2"),
    (RENTAL, "Who pays for repairs?", "4.1"),
    (RENTAL, "Can I rent a room to a friend?", "5.2"),
    (RENTAL, "Can someone else live in the flat?", "5.2"),
    (RENTAL, "How much is the deposit?", "3.1"),
    (RENTAL, "Will I get my deposit back?", "3.2"),
    (RENTAL, "Is there a penalty for paying late?", "2.3"),
    (RENTAL, "When does the agreement end?", "1.1"),
    (EMPLOYMENT, "How long is the probation?", "Clause 2"),
    (EMPLOYMENT, "What happens if I quit within a year?", "Clause 5"),
    (EMPLOYMENT, "Can I join a competitor after leaving?", "Clause 6"),
    (EMPLOYMENT, "When is salary paid?", "Clause 3"),
    (EMPLOYMENT, "What are my working hours?", "Clause 8"),
    (EMPLOYMENT, "How much notice do I give to resign?", "Clause 4"),
]


@pytest.fixture
def bm25_only(monkeypatch):
    """Force the fallback path CI uses when the embedding model isn't present."""
    monkeypatch.setattr(R, "_embedder", None)
    monkeypatch.setattr(R, "_embedder_failed", True)
    R.clear_cache()
    yield
    R.clear_cache()


def test_tokenize_folds_word_forms():
    assert set(R.tokenize("terminate terminated termination terminates")) == {"termin"}
    assert R.tokenize("60 days notice") == ["60", "day", "notic"]
    assert R.tokenize("Rs. 45,000") == ["rs", "45,000"]
    assert "the" not in R.tokenize("the Tenant")


def test_lay_terms_expand_to_legal_words():
    assert "sublet" in R.expand_query("Can I rent a room to my friend?")
    assert "terminate" in R.expand_query("Can I move out early?")
    assert R.expand_query("What is the rent?") == "What is the rent?"


def test_empty_document_returns_nothing():
    assert R.retrieve(Document("d", "x.txt", []), "anything") == []


def test_scores_are_relevances_best_first():
    r = R.retrieve(RENTAL, "What is the late fee?", k=3)
    assert len(r) == 3
    assert all(0.0 <= s <= 1.0 for _, s in r)
    assert "2.3" in r[0][0].text


def test_bm25_fallback_still_finds_exact_terms(bm25_only):
    assert not R.dense_available()
    r = R.retrieve(RENTAL, "Can I sublet the premises?", k=3)
    assert "5.2" in r[0][0].text
    assert r[0][1] == 1.0                      # BM25 relative to the best match


def test_bm25_fallback_always_returns_k(bm25_only):
    r = R.retrieve(RENTAL, "What is the late fee?", k=3)
    assert len(r) == 3 and "2.3" in r[0][0].text
    assert [s for _, s in r][1:] <= [r[0][1]] * 2
    none = R.retrieve(RENTAL, "zebra quantum", k=3)          # nothing matches at all
    assert len(none) == 3 and all(s == 0.0 for _, s in none)


def test_bm25_fallback_is_deterministic(bm25_only):
    a = [p.id for p, _ in R.retrieve(RENTAL, "deposit refund", k=5)]
    R.clear_cache()
    b = [p.id for p, _ in R.retrieve(RENTAL, "deposit refund", k=5)]
    assert a == b


@pytest.mark.skipif(not R.dense_available(), reason="embedding model not downloaded (see docs/MODEL_SETUP.md)")
def test_hybrid_accuracy_on_handwritten_questions():
    top1 = top3 = 0
    for doc, q, want in CASES:
        texts = [p.text for p, _ in R.retrieve(doc, q, k=3)]
        top1 += want in texts[0]
        top3 += any(want in t for t in texts)
    assert top3 == len(CASES)
    assert top1 >= len(CASES) - 3


@pytest.mark.skipif(not R.dense_available(), reason="embedding model not downloaded")
def test_unanswerable_question_scores_low():
    best = R.retrieve(RENTAL, "Can I keep a pet?", k=1)[0][1]
    answerable = R.retrieve(RENTAL, "How long is the notice period?", k=1)[0][1]
    assert best < 0.3 < answerable


def test_ask_sends_the_retrieved_clauses_to_the_model():
    sublet = next(p for p in RENTAL.passages if p.text.startswith("5.2"))
    stub = StubGemma(script=[json.dumps({
        "text": f"The document says the Tenant shall not sublet [{sublet.id}].",
        "citations": [{"passage_id": sublet.id, "quote": "The Tenant shall not sublet the Premises"}],
        "silent": False, "refused": False})])
    r = ask(RENTAL, "Can I rent a room to a friend?", client=stub)
    assert f"[{sublet.id}]" in stub.calls[0]          # the clause reached the prompt
    assert r.citations and r.citations[0].passage_id == sublet.id and not r.silent
