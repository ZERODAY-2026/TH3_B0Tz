"""tests/test_ui.py -- Deterministic tests for Person D's UI layer.

Tests app.contracts (the pipeline seam) and the render functions in
app.ui, using the team's StubGemma and test samples. No model server needed.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.contracts import DISCLAIMER, SILENT_TEXT, severity, tiers
from legallens.types import KINDS, LABELS, Analysis, Document, Finding, Passage

# -- fixtures ----------------------------------------------------------------

SAMPLE_DOC = Document(
    doc_id="test-01",
    source_name="test.txt",
    passages=[
        Passage(id="p1.c1", page=1, heading="Rent",
                text="Rent is Rs. 10,000 per month.", start=0, end=30),
        Passage(id="p1.c2", page=1, heading="Deposit",
                text="Deposit is Rs. 30,000.", start=31, end=55),
    ],
    extraction_warnings=[],
)

SAMPLE_FINDINGS = [
    Finding(id="f1", kind="obligation", party="Tenant",
            plain_text="Pay rent of Rs. 10,000.",
            quote="Rent is Rs. 10,000 per month.",
            passage_id="p1.c1", label="STATED", confidence="high"),
    Finding(id="f2", kind="right", party="Tenant",
            plain_text="Deposit is refundable.",
            quote="Deposit is Rs. 30,000.",
            passage_id="p1.c2", label="INTERPRETATION", confidence="medium"),
    Finding(id="f3", kind="penalty", party="Tenant",
            plain_text="Late fee applies.",
            quote="Late fee of Rs. 500.",
            passage_id="p1.c1", label="STATED", confidence="high"),
]

SAMPLE_ANALYSIS = Analysis(
    summary="This is a test rental agreement [p1.c1].",
    summary_citations=["p1.c1"],
    findings=SAMPLE_FINDINGS,
    coverage={"found": ["rent", "deposit"], "not_found": ["pets"]},
)


# -- contracts.py tests -------------------------------------------------------

class TestSeverityScoring:
    def test_penalty_high_stated_is_highest(self):
        f = Finding(id="f1", kind="penalty", party="Tenant",
                    plain_text="x", quote="x", passage_id="p1",
                    label="STATED", confidence="high")
        assert severity(f) == 5 * 1.0 * 1.0  # 5.0

    def test_right_low_interpretation_is_lowest(self):
        f = Finding(id="f2", kind="right", party="Tenant",
                    plain_text="x", quote="x", passage_id="p1",
                    label="INTERPRETATION", confidence="low")
        assert severity(f) == 1 * 0.4 * 0.8  # 0.32

    def test_severity_always_positive(self):
        for kind in KINDS:
            for label in LABELS:
                f = Finding(id="f", kind=kind, party=None,
                            plain_text="x", quote="x", passage_id="p1",
                            label=label, confidence="medium")
                assert severity(f) > 0


class TestTiers:
    def test_tiers_returns_three_buckets(self):
        t = tiers(SAMPLE_FINDINGS)
        assert set(t.keys()) == {"Critical", "Important", "Informational"}

    def test_penalty_is_critical(self):
        t = tiers(SAMPLE_FINDINGS)
        critical_kinds = [f.kind for f in t["Critical"]]
        assert "penalty" in critical_kinds

    def test_right_is_informational(self):
        t = tiers(SAMPLE_FINDINGS)
        info_kinds = [f.kind for f in t["Informational"]]
        assert "right" in info_kinds

    def test_empty_findings(self):
        t = tiers([])
        assert all(len(v) == 0 for v in t.values())


class TestConstants:
    def test_disclaimer_mentions_not_legal_advice(self):
        assert "not legal advice" in DISCLAIMER.lower()

    def test_silent_text_mentions_document(self):
        assert "document" in SILENT_TEXT.lower()


# -- sample documents tests ---------------------------------------------------

class TestSampleDocs:
    SAMPLES_DIR = Path(__file__).parent.parent / "data" / "samples"

    def test_samples_directory_exists(self):
        assert self.SAMPLES_DIR.exists()

    def test_rental_clear_exists(self):
        assert (self.SAMPLES_DIR / "rental_clear.txt").exists()

    def test_employment_standard_exists(self):
        assert (self.SAMPLES_DIR / "employment_standard.txt").exists()

    def test_rental_vague_exists(self):
        assert (self.SAMPLES_DIR / "rental_vague.txt").exists()

    def test_employment_conflict_exists(self):
        assert (self.SAMPLES_DIR / "employment_conflict.txt").exists()

    def test_injected_exists(self):
        assert (self.SAMPLES_DIR / "injected.txt").exists()

    def test_malformed_directory_has_files(self):
        malformed = self.SAMPLES_DIR / "malformed"
        assert malformed.exists()
        assert any(malformed.iterdir())

    def test_held_out_exists(self):
        held_out = Path(__file__).parent.parent / "data" / "held_out"
        assert held_out.exists()
        assert any(held_out.iterdir())

    def test_sample_files_not_empty(self):
        for f in self.SAMPLES_DIR.glob("*.txt"):
            assert f.stat().st_size > 50, f"{f.name} seems too small"
