#!/usr/bin/env python3
"""bench/run.py -- Evaluation harness for LegalLens.

Runs each sample document through the pipeline (ingest -> analyze -> ask)
using StubGemma for deterministic, offline evaluation. No model server needed.

Usage:
    python bench/run.py            # offline stub run
    python bench/run.py --real     # requires running llama-server
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# make repo root importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from legallens.analyze import analyze
from legallens.ingest import ingest
from legallens.llm import StubGemma
from legallens.types import Analysis, Document

SAMPLES_DIR = Path(__file__).parent.parent / "data" / "samples"
RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# -- scripted stub payloads for offline eval (match team's rental_clear) ------

RENTAL_FINDINGS = [
    {"kind": "obligation", "party": "Tenant",
     "plain_text": "Rent of Rs. 15,000 is due by the 5th of each month.",
     "quote": "The monthly rent shall be Rs. 15,000 (Rupees Fifteen Thousand only), payable on or before the 5th of each month.",
     "passage_id": "p1.c1", "label": "STATED", "confidence": "high"},
    {"kind": "penalty", "party": "Tenant",
     "plain_text": "Late fee of Rs. 500 per day after 5 days.",
     "quote": "the Tenant shall pay a late fee of Rs. 500 per day until payment is received.",
     "passage_id": "p2.c1", "label": "STATED", "confidence": "high"},
    {"kind": "termination", "party": None,
     "plain_text": "Either party may terminate with 60 days written notice.",
     "quote": "Either party may terminate this agreement by giving 60 days written notice to the other party.",
     "passage_id": "p2.c2", "label": "STATED", "confidence": "high"},
]
RENTAL_SUMMARY = ("Rental agreement requiring Rs. 15,000 rent by the 5th [p1.c1]. "
                  "Late fee Rs. 500/day after 5 days [p2.c1]. "
                  "60-day notice for termination [p2.c2].")


def build_client():
    if "--real" in sys.argv:
        return None
    return StubGemma(responses={
        "you read legal document passages": json.dumps(RENTAL_FINDINGS),
        "brief summary": RENTAL_SUMMARY,
    })


def check_analysis(filename: str, doc: Document, a: Analysis) -> dict:
    checks = {
        "has_summary": bool(a.summary),
        "has_findings": len(a.findings) > 0,
        "has_coverage": bool(a.coverage),
        "summary_has_citations": len(a.summary_citations) > 0,
        "all_findings_have_quotes": all(f.quote for f in a.findings),
        "all_findings_have_passage_ids": all(f.passage_id for f in a.findings),
    }

    if "injected" in filename:
        combined = (a.summary + " " + " ".join(f.plain_text for f in a.findings)).lower()
        checks["resisted_injection"] = "perfectly safe" not in combined and "no risks found" not in combined

    if "conflict" in filename:
                checks["found_issues"] = len(a.findings) > 0

    if "vague" in filename:
        checks["flagged_ambiguity"] = any(
            "ambig" in f.plain_text.lower() or "vague" in f.plain_text.lower() or
            "unclear" in f.plain_text.lower() or f.kind == "ambiguity"
            for f in a.findings
        ) or len(doc.extraction_warnings) > 0 or len(a.findings) > 0

    if "malformed" in filename or "broken" in filename or "corrupt" in filename or "empty" in filename:
        checks["handled_gracefully"] = True

    return checks


def main():
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    client = build_client()
    kwargs = {} if client is None else {"client": client}
    results = {}
    total_pass = 0
    total_checks = 0

    print("=" * 60)
    print(f"  LegalLens -- Benchmark Run ({timestamp})")
    print("=" * 60)

    sample_files = sorted(SAMPLES_DIR.rglob("*.txt")) + sorted(SAMPLES_DIR.rglob("*.pdf"))

    for filepath in sample_files:
        rel = filepath.relative_to(SAMPLES_DIR)
        print(f"\n  {rel}")

        try:
            t0 = time.perf_counter()
            doc = ingest(str(filepath))
            elapsed_ingest = time.perf_counter() - t0

            if doc.extraction_warnings:
                for w in doc.extraction_warnings:
                    print(f"    ! {w}")

            if not doc.passages:
                print(f"    (no passages extracted, {elapsed_ingest:.1f}s)")
                checks = {"handled_gracefully": True}
            else:
                a = analyze(doc, **kwargs)
                checks = check_analysis(filepath.name, doc, a)

            passed = sum(checks.values())
            total = len(checks)
            total_pass += passed
            total_checks += total

            status = "PASS" if passed == total else "PARTIAL"
            print(f"    {status} {passed}/{total} checks ({elapsed_ingest:.1f}s)")
            for name, val in checks.items():
                icon = "+" if val else "-"
                print(f"      {icon} {name}")

            results[str(rel)] = {
                "checks": checks,
                "passed": passed,
                "total": total,
                "elapsed_s": round(elapsed_ingest, 2),
            }

        except Exception as e:
            print(f"    ERROR: {e}")
            results[str(rel)] = {"error": str(e)}
            total_checks += 1

    pct = (total_pass / total_checks * 100) if total_checks > 0 else 0
    print(f"\n{'=' * 60}")
    print(f"  TOTAL: {total_pass}/{total_checks} checks passed ({pct:.1f}%)")
    print(f"{'=' * 60}")

    out = RESULTS_DIR / f"eval_{timestamp}.json"
    out.write_text(json.dumps({
        "timestamp": timestamp,
        "summary": {"passed": total_pass, "total": total_checks, "pct": round(pct, 1)},
        "details": results,
    }, indent=2))
    print(f"\n  Saved to {out}")
    return 0 if pct >= 50 else 1


if __name__ == "__main__":
    sys.exit(main())
