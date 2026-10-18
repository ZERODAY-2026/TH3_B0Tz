"""Read-only SQL validation for DataMind (Person A, H2-H3).

Layer 1 of defence-in-depth: anything the LLM drafts is parsed with sqlglot
and rejected unless it is a single read-only SELECT against known tables.
B re-enforces read-only at the Snowflake execution layer (layer 2).
"""
from __future__ import annotations

import re

import sqlglot
from sqlglot import exp

from .types import Schema

# Snowflake functions that execute something or reach outside the query
# engine; none belong in a generated SELECT.
FORBIDDEN_FUNCTIONS = {
    "EXECUTE_IMMEDIATE",
    "LOGIN", "LOGOUT",
    "READ_FILE", "WRITE_FILE",
    "STAGE", "PUT", "GET",
    "SYSTEM$", "RESULT_SCAN",  # chases a prior query's results; skip it
}

_WRITE_NODE_TYPES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge,
    exp.Create, exp.Alter, exp.Drop, exp.TruncateTable,
    exp.Grant, exp.Revoke, exp.Copy, exp.Set,
    exp.Use, exp.Commit, exp.Rollback,
)


class ValidationError(Exception):
    """Raised with a coach-able message that is fed back to the LLM on retry."""


def validate_sql(sql: str, schema: Schema) -> str:
    """Return cleaned SQL if read-only & schema-valid, else raise ValidationError.

    The message is written for the model to act on (used as the retry hint),
    so it names the offending table/function rather than being generic.
    """
    if not sql or not sql.strip():
        raise ValidationError("empty SQL")

    lowered = sql.strip().lower()
    if lowered.startswith("with"):
        # CTEs are fine, but a leading WITH ... INSERT/UPDATE is not; parse below
        pass

    try:
        statements = [
            s for s in sqlglot.parse(sql, dialect="snowflake") if s is not None
        ]
    except sqlglot.errors.ParseError as e:
        raise ValidationError(f"SQL does not parse: {e}") from e
    if len(statements) > 1:
        raise ValidationError("only one statement allowed")
    tree = statements[0]

    if not isinstance(tree, exp.Select) and not (
        isinstance(tree, exp.Union) or isinstance(tree, exp.Subquery)
    ):
        if isinstance(tree, _WRITE_NODE_TYPES) or isinstance(
            tree, (exp.Describe, exp.Command)
        ):
            raise ValidationError(
                "query must be a single read-only SELECT statement; "
                f"got {type(tree).__name__}"
            )
        raise ValidationError(
            f"expected a SELECT statement, got {type(tree).__name__}"
        )

    # CTE bodies must be SELECTs too.
    for cte in tree.find_all(exp.CTE):
        if isinstance(cte.this, _WRITE_NODE_TYPES):
            raise ValidationError("WITH clause contains a write statement")

    # Unknown tables (CTE aliases are legitimate references, allow them).
    cte_names = {cte.alias_or_name.upper() for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        bare = table.name.upper()
        if bare and bare not in schema and bare not in cte_names:
            raise ValidationError(
                f"unknown table {bare!r}; valid tables: "
                + ", ".join(sorted(schema))
            )

    # Forbidden functions (also catches string-built dynamic SQL attempts).
    for func in tree.find_all(exp.Anonymous):
        fname = (func.this or "").upper() if isinstance(func.this, str) else ""
        if fname in FORBIDDEN_FUNCTIONS or fname.startswith("SYSTEM$"):
            raise ValidationError(f"function {fname} is not allowed")
    if re.search(r"\bexecute\s+immediate\b", sql, re.IGNORECASE):
        raise ValidationError("EXECUTE IMMEDIATE is not allowed")
    if re.search(r"\$\{", sql):
        raise ValidationError("string interpolation is not allowed in SQL")

    return sql.strip()


def classify_question(question: str) -> str:
    """Rough category hint for the SQLGEN prompt (helps Gemma pick a shape)."""
    q = question.lower()
    if re.search(r"\b(top|highest|rank|best|most|largest)\b", q):
        return "ranking"
    if re.search(r"\b(trend|over time|by year|by month|monthly|yearly|growth)\b", q):
        return "time-series"
    if re.search(r"\b(how many|count|total|average|avg|sum|percentage|share)\b", q):
        return "aggregate"
    if re.search(r"\b(which|what|who|list|show|find)\b", q):
        return "lookup"
    return "general"
