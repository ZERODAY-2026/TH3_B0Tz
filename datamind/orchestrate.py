"""DataMind orchestrator (Person A) — answer() and the retry loop.

Pipeline per question:
  classify -> Gemma drafts SQL -> sqlguard validates -> (up to 2 retries,
  error fed back) -> run_query() executes -> Gemma explains rows -> Answer.

Also owns: ambiguity / unsupported-request handling, empty-result honesty,
and follow-up context (H6-H8): a rolling window of prior Q/A pairs is folded
into the SQLGEN prompt so "what about last year?" resolves against the
previous question's tables and filters.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from .llm import (
    GemmaClient,
    StubGemmaClient,
    build_explain_messages,
    build_retry_messages,
    build_sqlgen_messages,
    parse_llm_json,
    strip_sql,
)
from .sqlguard import ValidationError, classify_question, validate_sql
from .types import Answer, QueryResult, Schema, format_schema

MAX_RETRIES = 2  # plan: "on invalid SQL, feed the error back and retry (max 2)"

_AMBIGUOUS_PATTERNS = [
    r"\bbest\b",
    r"\bgood\b",
    r"\bnice\b",
    r"\bpopular\b",
    r"\brecent\b",
    r"\btop products?\b",
    r"\bsome\b",
    r"\blatest\b",
    r"which one",
]
_AMBIGUOUS_RE = re.compile("|".join(_AMBIGUOUS_PATTERNS), re.IGNORECASE)


def _looks_ambiguous(question: str) -> bool:
    """Cheap pre-filter: if the phrase itself is vague, ask before querying."""
    return bool(_AMBIGUOUS_RE.search(question))


@dataclass
class DataMind:
    """The service object Person C's CLI/UI and D's bench call into."""

    client: GemmaClient | StubGemmaClient
    schema: Schema
    run_query: Callable[[str], QueryResult] | None = None
    max_retries: int = MAX_RETRIES

    def __post_init__(self) -> None:
        if self.run_query is None:
            self.run_query = _default_run_query()
        self._history: list[dict[str, str]] = []

    # -- public API ---------------------------------------------------------

    def answer(self, question: str) -> Answer:
        """End-to-end: question -> executed query -> evidenced answer."""
        # Follow-up resolution: a pronoun-led short question inherits context.
        context = self._resolve_followup(question)
        target = context["effective_question"]

        # Layer 0: cheap ambiguity gate before spending a Gemma call.
        if _looks_ambiguous(target) and not context["is_followup"]:
            return Answer(
                text=(
                    "That question is a bit vague - could you say what you mean by "
                    "the highlighted term? For example, \"top 5 customers by total "
                    "spend\" instead of \"best customers\"."
                ),
                ambiguous=True,
                model=self.client.model,
            )

        schema_text = format_schema(self.schema)
        if self._history:
            history_lines = "\n".join(
                f"Q: {h['q']}\nSQL: {h['sql']}" for h in self._history[-3:]
            )
            schema_text += (
                "\n\nPrevious turns (resolve follow-ups against these):\n"
                + history_lines
            )

        messages = build_sqlgen_messages(
            schema_text, target, question_kind=classify_question(target)
        )

        last_error = ""
        for attempt in range(1 + self.max_retries):
            raw = self.client.chat(messages)
            try:
                payload = parse_llm_json(raw)
            except ValueError as e:
                last_error = f"model output was not valid JSON: {e}"
                messages = build_retry_messages(
                    schema_text, target, "", last_error
                )
                continue

            if not payload.get("ok", True):
                reason = str(payload.get("reason", "")).lower()
                if "ambiguous" in reason:
                    return self._clarify(target, payload)
                if "unsupported" in reason:
                    return self._refuse_unsupported(target, payload)
                last_error = f"model declined: {payload.get('reason')}"
                messages = build_retry_messages(
                    schema_text, target, "", last_error
                )
                continue

            sql = strip_sql(str(payload.get("sql", "")))
            try:
                validated = validate_sql(sql, self.schema)
            except ValidationError as e:
                last_error = str(e)
                messages = build_retry_messages(
                    schema_text, target, sql, last_error
                )
                continue

            result = self.run_query(validated)
            if result is None or result.error:
                err = (result.error if result else None) or "executor returned nothing"
                last_error = f"execution failed: {err}"
                messages = build_retry_messages(
                    schema_text, target, validated, last_error
                )
                continue

            return self._explain(
                question=target,
                sql=validated,
                result=result,
                draft_assumptions=payload.get("assumptions", []),
                draft_tables=payload.get("tables", []),
            )

        # Retries exhausted: report honestly, never guess.
        return Answer(
            text=(
                "I could not write a safe query for that after "
                f"{self.max_retries} retries. Last problem: {last_error}. "
                "Try rephrasing or naming the table/column you mean."
            ),
            model=self.client.model,
        )

    # -- helpers -------------------------------------------------------------

    def _explain(
        self,
        question: str,
        sql: str,
        result: QueryResult,
        draft_assumptions: list,
        draft_tables: list,
    ) -> Answer:
        messages = build_explain_messages(
            question, sql, result.columns, result.rows
        )
        explanation = ""
        assumptions = [str(a) for a in draft_assumptions]
        try:
            payload = parse_llm_json(self.client.chat(messages))
            explanation = str(payload.get("explanation", ""))
            assumptions += [str(a) for a in payload.get("assumptions", [])]
        except Exception:  # noqa: BLE001 - explanation is best-effort
            explanation = ""

        if not result.rows:
            # Empty result: honest wording, no fabricated numbers (M6).
            explanation = (
                "The query ran successfully but returned no rows. "
                + (
                    "Most likely the filters (e.g. a name, date or category in the "
                    "WHERE clause) do not match anything in the data."
                    if "where" in sql.lower()
                    else "The table may simply have no matching data for this filter."
                )
            )

        self._history.append({"q": question, "sql": sql})

        sql_tables = sorted(
            {
                t.name.upper()
                for t in _tables_in(sql, self.schema)
            }
        )
        tables_used = sorted(set(sql_tables) | {str(t).upper() for t in draft_tables})

        return Answer(
            text=explanation or "See evidence for the raw result.",
            sql=sql,
            query_result=result,
            explanation=explanation,
            assumptions=assumptions,
            ambiguous=False,
            unsupported=False,
            model=self.client.model,
        )

    def _clarify(self, question: str, payload: dict) -> Answer:
        detail = payload.get("reason", "ambiguous")
        return Answer(
            text=(
                "I want to make sure I answer the right thing. The question seems "
                f"ambiguous ({detail}). Could you rephrase it more specifically, e.g. "
                "name the exact column, date range or ranking rule you want?"
            ),
            ambiguous=True,
            model=self.client.model,
        )

    def _refuse_unsupported(self, question: str, payload: dict) -> Answer:
        detail = payload.get("reason", "unsupported")
        return Answer(
            text=(
                "I don't think the loaded data can answer that "
                f"({detail}). The available tables are: "
                + ", ".join(sorted(self.schema))
                + ". Ask something over those and I'll query them."
            ),
            unsupported=True,
            model=self.client.model,
        )

    # -- follow-up context (H6-H8) -------------------------------------------

    def _resolve_followup(self, question: str) -> dict[str, object]:
        """Detect follow-ups and fold in prior context.

        Short questions with pronouns/deixis ("and in 2024?", "which of those
        was cheapest?") get the previous question appended as context.
        """
        followup_markers = re.compile(
            r"^(and|also|what about|how about|then|which of those|"
            r"of those|among those|for those)\b",
            re.IGNORECASE,
        )
        is_followup = bool(followup_markers.search(question.strip())) and bool(
            self._history
        )
        if not is_followup:
            return {"is_followup": False, "effective_question": question}
        prior = self._history[-1]
        effective = (
            f"{question} (referring to the earlier question: {prior['q']!r}, "
            f"which used SQL: {prior['sql']!r})"
        )
        return {"is_followup": True, "effective_question": effective}

    def reset(self) -> None:
        self._history.clear()


# ---------------------------------------------------------------------------

def _tables_in(sql: str, schema: Schema) -> list:
    from sqlglot import exp
    import sqlglot

    try:
        tree = sqlglot.parse_one(sql, dialect="snowflake")
        return [t for t in tree.find_all(exp.Table)]
    except Exception:  # noqa: BLE001 - best-effort for evidence labels
        return []


def _default_run_query():
    """Prefer B's real executor; fall back to the stub."""
    try:
        from .snowflake_client import run_query as real_run_query

        return real_run_query
    except ImportError:
        from .stub_executor import run_query as stub_run_query

        return stub_run_query
