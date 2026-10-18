"""Contract tests for the H0 shared types."""
import dataclasses

from legallens.types import Analysis, Citation, Document, Finding, Passage, Reply, VerifyResult

from .samples import RENTAL


def test_finding_fields_match_plan():
    names = {f.name for f in dataclasses.fields(Finding)}
    assert names == {"id", "kind", "party", "plain_text", "quote", "passage_id",
                     "label", "confidence", "flags", "escalation_note"}


def test_analysis_has_summary_citations():
    names = {f.name for f in dataclasses.fields(Analysis)}
    assert "summary_citations" in names  # 6.1.6 amendment


def test_reply_defaults():
    r = Reply(text="x")
    assert r.citations == [] and r.silent is False and r.refused is False


def test_document_passage_lookup():
    assert RENTAL.passage("p1.c1") is not None
    assert RENTAL.passage("p9.c9") is None
