"""Smoke test: analyze() + ask() end-to-end against the stub Gemma.

No model server needed — StubGemma returns scripted payloads and the
permissive stubs stand in for B's retrieve() and C's verify() until they
land. With a real llama-server running, swap --real in.

Usage:
    python smoke.py            # offline stub run (no keys, no server)
    python smoke.py --real     # real Gemma via 127.0.0.1:8080
    python smoke.py --file data/samples/rental_clear.pdf   # real file + real Gemma
"""
from __future__ import annotations

import json
import sys

from legallens.analyze import ask, analyze
from tests.samples import INJECTED, RENTAL

FINDINGS = [
    {"kind": "obligation", "party": "Tenant",
     "plain_text": "The document states the Tenant must pay Rs. 15,000 rent by "
                   "the 5th of each month.",
     "quote": "The monthly rent shall be Rs. 15,000 (Rupees Fifteen Thousand only), "
              "payable on or before the 5th of each month.",
     "passage_id": "p1.c1", "label": "STATED", "confidence": "high"},
    {"kind": "penalty", "party": "Tenant",
     "plain_text": "The document states a late fee of Rs. 500 per day applies after 5 days.",
     "quote": "the Tenant shall pay a late fee of Rs. 500 per day",
     "passage_id": "p2.c1", "label": "STATED", "confidence": "high"},
    {"kind": "termination", "party": None,
     "plain_text": "The document states either party may terminate with 60 days "
                   "written notice.",
     "quote": "Either party may terminate this agreement by giving 60 days written "
              "notice to the other party.",
     "passage_id": "p2.c2", "label": "STATED", "confidence": "high"},
]
SUMMARY = ("This rental agreement requires rent of Rs. 15,000 by the 5th of each "
           "month [p1.c1]. A late fee of Rs. 500 per day applies after 5 days "
           "[p2.c1]. Either party may terminate with 60 days written notice [p2.c2].")
QA_OK = {
    "text": "The document states a late fee of Rs. 500 per day after 5 days [p2.c1].",
    "citations": [{"passage_id": "p2.c1",
                   "quote": "the Tenant shall pay a late fee of Rs. 500 per day"}],
    "silent": False, "refused": False, "escalation_note": None,
}
QA_SILENT = {
    "text": "The document does not appear to say anything about this.",
    "citations": [], "silent": True, "refused": False, "escalation_note": None,
}


def build_client():
    if "--real" in sys.argv:
        return None  # analyze() falls through to the real HTTP client
    from legallens.llm import StubGemma

    return StubGemma(responses={
        "you read legal document passages": json.dumps(FINDINGS),
        "brief summary": SUMMARY,
        "answering a question about a legal document": json.dumps(QA_OK),
    })


def run_file(path: str) -> None:
    """Real file end to end: ingest() -> analyze() -> ask() on real Gemma."""
    import time

    from legallens.ingest import ingest

    doc = ingest(path)
    print(f"=== ingest({doc.source_name}): {len(doc.passages)} passages ===")
    for w in doc.extraction_warnings:
        print(f"  ! {w}")
    if not doc.passages:
        return
    t0 = time.perf_counter()
    a = analyze(doc)
    print(f"\n=== analyze(): {time.perf_counter() - t0:.0f}s ===")
    print(f"summary: {a.summary}\n")
    for f in a.findings:
        state = "UNVERIFIED" if "unverified" in f.flags else "ok"
        print(f"[{f.kind}/{f.label}/{state}] {f.plain_text}")
        print(f"    quote: \"{f.quote[:80]}\"  ({f.passage_id})")
    print(f"coverage: {a.coverage}")
    for q in ("What is the notice period?", "Can I keep a pet?", "Is the late fee enforceable?"):
        t0 = time.perf_counter()
        r = ask(doc, q)
        print(f"\n=== ask({q!r}): {time.perf_counter() - t0:.0f}s  silent={r.silent} refused={r.refused}")
        print(f"text: {r.text}")
        print(f"citations: {[(c.passage_id, c.quote[:50]) for c in r.citations]}")


def main() -> None:
    if "--file" in sys.argv:
        run_file(sys.argv[sys.argv.index("--file") + 1])
        return
    client = build_client()
    kwargs = {} if client is None else {"client": client}

    print("=== analyze() on rental sample ===")
    a = analyze(RENTAL, **kwargs)
    print(f"summary: {a.summary}\n")
    print(f"citations: {a.summary_citations}\n")
    for f in a.findings:
        print(f"[{f.kind}/{f.label}] {f.plain_text}")
        print(f"    quote: \"{f.quote[:70]}...\"  ({f.passage_id})")
    print(f"coverage: {a.coverage}\n")

    print("=== ask(): answerable ===")
    r = ask(RENTAL, "what is the late fee?", **kwargs)
    print(f"text: {r.text}")
    print(f"citations: {[(c.passage_id, c.quote[:40]) for c in r.citations]}\n")

    if client is not None:
        client.responses["answering a question about a legal document"] = json.dumps(QA_SILENT)
    print("=== ask(): silent (pet policy) ===")
    r = ask(RENTAL, "what is the pet policy?", **kwargs)
    print(f"text: {r.text}  (silent={r.silent})\n")

    print("=== ask(): verdict -> refused in code ===")
    r = ask(RENTAL, "is this enforceable?", **kwargs)
    print(f"text: {r.text}  (refused={r.refused})\n")

    print("=== analyze() on injected doc ===")
    if client is not None:
        client.responses["you read legal document passages"] = json.dumps([
            {"kind": "obligation", "party": "Tenant",
             "plain_text": "The document states rent of Rs. 12,000 is payable in advance.",
             "quote": "The monthly rent shall be Rs. 12,000, payable in advance.",
             "passage_id": "p1.c1", "label": "STATED", "confidence": "high"}])
        client.responses["brief summary"] = "Rent of Rs. 12,000 is payable in advance [p1.c1]."
    a = analyze(INJECTED, **kwargs)
    joined = (a.summary + " " + " ".join(f.plain_text for f in a.findings)).lower()
    print(f"summary: {a.summary}")
    print(f"injection leaked into output: {'fully legal' in joined or 'safe to sign' in joined}")


if __name__ == "__main__":
    main()
