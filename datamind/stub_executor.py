"""Stub run_query() for H3-H4 wiring (Person A).

Deterministic, in-memory stand-in for B's ``datamind.snowflake_client.run_query``.
It validates SQL with the same sqlguard rules, then returns tiny hand-checked
result sets so the explanation prompt, ambiguity handling and evidence flow
can all be built and tested before Snowflake credentials exist.

Delete or ignore once ``datamind/snowflake_client.py`` lands (orchestrate.py
imports the real one automatically when it is importable).
"""
from __future__ import annotations

from .sqlguard import validate_sql
from .types import QueryResult, Schema

# Bare-table -> sample rows for the demo schema in tests/stub data.
STUB_TABLES: dict[str, list[tuple]] = {
    "CUSTOMER": [
        ("Customer#000000001", " shopper1@example.com ", "INDIA", 1000.50),
        ("Customer#000000002", "shopper2@example.com", "INDIA", 250.00),
        ("Customer#000000003", "shopper3@example.com", "USA", 75.25),
    ],
    "STORE_SALES": [
        ("2026-01-05", "Customer#000000001", 1, 2, 25.50),
        ("2026-01-06", "Customer#000000002", 1, 3, 40.00),
        ("2026-01-07", "Customer#000000003", 2, 1, 12.75),
        ("2026-01-08", "Customer#000000001", 2, 4, 60.00),
    ],
    "ITEM": [
        (1, "Wireless Mouse", "ELECTRONICS", 25.50),
        (2, "Notebook", "STATIONERY", 5.00),
        (3, "Desk Lamp", "HOME", 18.00),
        ( 4, "USB-C Cable", "ELECTRONICS", 8.00),
    ],
}

STUB_COLUMNS: dict[str, list[str]] = {
    "CUSTOMER": ["C_CUSTOMER_SK", "C_EMAIL_ADDRESS", "C_COUNTRY", "C_TOTAL_SPEND"],
    "STORE_SALES": ["SS_SOLD_DATE", "SS_CUSTOMER_SK", "SS_ITEM_SK", "SS_QUANTITY", "SS_SALES_PRICE"],
    "ITEM": ["I_ITEM_SK", "I_ITEM_NAME", "I_CATEGORY", "I_PRICE"],
}


def run_query(sql: str, schema: Schema | None = None) -> QueryResult:
    """Validate then 'execute' against tiny fixed tables.

    Supports SELECT * FROM <table> LIMIT n and full-table scans; it does not
    evaluate expressions — that is B's job. It exists to exercise A's retry
    loop, explanation prompt and empty-result handling with plausible shapes.
    """
    effective_schema = schema or {
        name: name for name in STUB_TABLES  # type: ignore[misc]
    }
    try:
        clean = validate_sql(sql, _bare_schema())
    except Exception as e:  # noqa: BLE001 - stub surface mirrors B's error path
        return QueryResult(columns=[], rows=[], error=str(e))

    import re

    m = re.search(r"from\s+([A-Za-z_][\w$]*)", clean, re.IGNORECASE)
    if not m:
        return QueryResult(columns=[], rows=[], error="stub: only single-table FROM supported")
    table = m.group(1).upper()
    if table not in STUB_TABLES:
        return QueryResult(columns=[], rows=[], error=f"stub: table {table} not in stub dataset")

    rows = list(STUB_TABLES[table])
    lim = re.search(r"limit\s+(\d+)", clean, re.IGNORECASE)
    if lim:
        rows = rows[: int(lim.group(1))]

    return QueryResult(
        columns=STUB_COLUMNS[table],
        rows=rows,
        query_id=f"stub-{abs(hash(clean)) % 10**8:08d}",
        row_count=len(rows),
        warehouse_credits_used=0.0,
    )


def _bare_schema() -> Schema:
    """Schema view of the stub tables (bare names, as sqlguard expects)."""
    from .types import ColumnInfo, TableInfo

    schema: Schema = {}
    for name, cols in STUB_COLUMNS.items():
        schema[name] = TableInfo(
            name=f"STUB.{name}",
            columns=[ColumnInfo(c) for c in cols],
            description="stub table",
        )
    return schema
