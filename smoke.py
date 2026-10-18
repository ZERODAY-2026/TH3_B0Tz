"""Smoke test: run answer() end-to-end against the stub executor.

Usage:
    python smoke.py                      # stub Gemma + stub executor (no keys)
    python smoke.py --real               # real Gemma endpoint from .env
"""
from __future__ import annotations

import sys

from datamind.orchestrate import DataMind
from datamind.stub_executor import _bare_schema, run_query


def main() -> None:
    real = "--real" in sys.argv
    if real:
        from datamind.llm import GemmaClient

        client = GemmaClient()
    else:
        from datamind.llm import StubGemmaClient

        client = StubGemmaClient(responses={
            "items": {"ok": True, "sql": "SELECT * FROM ITEM LIMIT 50",
                      "assumptions": ["limited to 50 rows"], "tables": ["ITEM"]},
            "customers": {"ok": True, "sql": "SELECT * FROM CUSTOMER LIMIT 50",
                          "assumptions": ["limited to 50 rows"],
                          "tables": ["CUSTOMER"]},
            "weather": {"ok": False, "reason": "unsupported", "sql": "",
                        "assumptions": [], "tables": []},
        })

    dm = DataMind(client=client, schema=_bare_schema(), run_query=run_query)

    questions = [
        "list the items",
        "what are the best items?",           # ambiguous -> clarify
        "what is the weather tomorrow?",      # unsupported (stub declines)
        "show me the customers",
    ]
    for q in questions:
        a = dm.answer(q)
        print("=" * 70)
        print(f"Q: {q}")
        print(f"A: {a.text[:200]}")
        print(f"   ambiguous={a.ambiguous} unsupported={a.unsupported} "
              f"model={a.model}")
        if a.sql:
            print(f"SQL: {a.sql}")
        if a.query_result:
            r = a.query_result
            print(f"rows={r.row_count} query_id={r.query_id} err={r.error}")


if __name__ == "__main__":
    main()
