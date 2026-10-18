#!/usr/bin/env python3
"""bench/citation_accuracy.py -- Measures whether cited passages exist in source.

Citation Accuracy = (citations found in source) / (total citations)
Uses StubGemma offline; pass --real for live model.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from legallens.analyze import analyze
from legallens.ingest import ingest
from legallens.llm import StubGemma

SAMPLES_DIR = Path(__file__).parent.parent / "data" / "samples"
RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

STUB_FINDINGS = [
    {"kind": "obligation", "party": "Tenant",
     "plain_text": "Rent of Rs. 15,000 due by the 5th.",
     "quote": "The monthly rent shall be Rs. 15,000 (Rupees Fifteen Thousand only), payable on or before the 5th of each month.",
     "passage_id": "p1.c1", "label": "STATED", "confidence": "high"},
]
STUB_SUMMARY = "Rent of Rs. 15,000 by the 5th [p1.c1]."


def build_client():
    if "--real" in sys.argv:
        return None
    return StubGemma(responses={
        "you read legal document passages": json.dumps(STUB_FINDINGS),
        "brief summary": STUB_SUMMARY,
    })


def measure(filepath: Path, client) -> dict:
    source_text = filepath.read_text(encoding="utf-8", errors="replace").lower()
    doc = ingest(str(filepath))

    if not doc.passages:
        return {"file": filepath.name, "total_citations": 0, "accuracy": None,
                "note": "No passages extracted"}

    kwargs = {} if client is None else {"client": client}
    a = analyze(doc, **kwargs)

    # check if finding quotes exist in source
    total = len(a.findings)
    found = 0
    details = []
    for f in a.findings:
        q = f.quote.lower().strip()
        is_found = q in source_text if q else False
        if is_found:
            found += 1
        details.append({"quote": f.quote[:80], "found": is_found, "passage_id": f.passage_id})

    return {
        "file": filepath.name,
        "total_citations": total,
        "found_in_source": found,
        "accuracy": round(found / total, 3) if total > 0 else None,
        "details": details,
    }


def main():
    print("  Citation Accuracy Evaluation\n")
    client = build_client()
    results = []

    for fp in sorted(SAMPLES_DIR.glob("*.txt")):
        r = measure(fp, client)
        results.append(r)
        acc = f"{r['accuracy']:.1%}" if r["accuracy"] is not None else "N/A"
        print(f"  {r['file']}: {acc} ({r.get('found_in_source', 0)}/{r['total_citations']})")

    with_citations = [r for r in results if r["accuracy"] is not None]
    if with_citations:
        overall = sum(r["accuracy"] for r in with_citations) / len(with_citations)
        print(f"\n  Overall: {overall:.1%}")

    out = RESULTS_DIR / "citation_accuracy.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"  Saved to {out}")


if __name__ == "__main__":
    main()
