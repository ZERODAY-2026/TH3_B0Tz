"""H0-agreed shared interface types for DataMind.

Single source of truth for the dataclasses every lane codes against:
B constructs ``QueryResult`` in ``snowflake_client``, A constructs ``Answer``
in ``orchestrate``, C consumes both for ``EvidenceReport``. Field names match
PLAN.md exactly — do not rename without updating the plan.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ColumnInfo:
    name: str
    type: str = ""
    comment: str = ""


@dataclass
class TableInfo:
    # Fully qualified, e.g. SNOWFLAKE_SAMPLE_DATA.TPCDS_SF10TCL.CUSTOMER
    name: str
    columns: list[ColumnInfo] = field(default_factory=list)
    description: str = ""

    @property
    def bare_name(self) -> str:
        return self.name.split(".")[-1]


# Key: bare table name, upper-cased.
Schema = dict[str, TableInfo]


def format_schema(schema: Schema) -> str:
    """Render the schema as prompt-friendly text (one TABLE line per table)."""
    lines = []
    for table in schema.values():
        cols = ", ".join(f"{c.name} {c.type}".rstrip() for c in table.columns)
        line = f"TABLE {table.name} ({cols})"
        if table.description:
            line += f" -- {table.description}"
        lines.append(line)
    return "\n".join(lines)


@dataclass
class QueryResult:
    """B provides: one executed query's outcome (run_query return type)."""

    columns: list[str]
    rows: list[tuple]
    query_id: str | None = None
    row_count: int = 0
    error: str | None = None
    warehouse_credits_used: float = 0.0

    def __post_init__(self) -> None:
        if not self.row_count:
            self.row_count = len(self.rows)


@dataclass
class Answer:
    """A provides: the end-to-end response to one question (answer() return type)."""

    text: str
    sql: str | None = None
    query_result: QueryResult | None = None
    explanation: str = ""
    assumptions: list[str] = field(default_factory=list)
    ambiguous: bool = False
    unsupported: bool = False
    model: str = ""
