"""Gemma client for DataMind (Person A).

Any OpenAI-compatible endpoint serving Gemma works: Ollama, LM Studio, vLLM
self-hosted, or Google AI Studio's OpenAI-compatible route. The client is
 deliberately thin — prompts live here as plain functions so they are easy
to tune at H8, and callers pass/parse JSON dicts, not SDK objects.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .config import Settings

# --- question interpretation / SQL generation -------------------------------

SQLGEN_SYSTEM = """You are a careful data analyst who writes Snowflake SQL.

Rules:
- Output ONLY a JSON object, no markdown fences, no prose.
- Schema: {schema}
- The target kind for this question is: {question_kind}
- Use ONLY tables and columns that appear in the schema above. Never invent tables or columns.
- Generate SELECT queries only. No INSERT, UPDATE, DELETE, MERGE, CREATE, ALTER, DROP, TRUNCATE, GRANT, COPY, CALL, or WITH ... DML.
- Add a LIMIT (default 50, at most 1000) whenever the result could be more than a handful of rows.
- If the question is ambiguous or cannot be answered with the schema, still return JSON but set "ok" to false and explain in "reason".
- If column values referenced in the question (names, categories, dates) are not clearly identifiable, set "ok" to false with reason "ambiguous".
- If the question asks for something the schema has no data for at all, set "ok" to false with reason "unsupported".

Return exactly this shape:
{{"ok": true, "sql": "SELECT ...", "reason": "", "assumptions": ["..."], "tables": ["CUSTOMER"]}}
or
{{"ok": false, "sql": "", "reason": "ambiguous" | "unsupported" | "<specific problem>", "assumptions": [], "tables": []}}"""

SQLGEN_RETRY = """Your previous SQL was rejected.

Previous SQL:
{previous}

Problem:
{problem}

Rewrite the query. Schema again:
{schema}

Remember: SELECT-only, only schema tables/columns, LIMIT for row-heavy results,
same JSON shape as before. If it genuinely cannot be written from this schema,
return ok=false with reason "ambiguous" or "unsupported"."""


def build_sqlgen_messages(
    schema_text: str, question: str, question_kind: str = "general"
) -> list[dict[str, str]]:
    system = SQLGEN_SYSTEM.format(schema=schema_text, question_kind=question_kind)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Question: {question}"},
    ]


def build_retry_messages(
    schema_text: str,
    question: str,
    previous_sql: str,
    problem: str,
) -> list[dict[str, str]]:
    return [
        *build_sqlgen_messages(schema_text, question),
        {
            "role": "assistant",
            "content": json.dumps({"ok": True, "sql": previous_sql}),
        },
        {
            "role": "user",
            "content": SQLGEN_RETRY.format(
                previous=previous_sql, problem=problem, schema=schema_text
            ),
        },
    ]


# --- explanation ---------------------------------------------------------

EXPLAIN_SYSTEM = """You explain SQL query results in plain language for a business user.

You are given: the question, the SQL that ran, the columns, and up to a few
result rows. Explain the answer in 2-4 sentences: state the finding first,
then how the query arrived at it (which tables, what was filtered/aggregated).

Rules:
- Use ONLY numbers and values present in the rows. NEVER compute new numbers, averages or sums yourself — the query already did the math.
- If the rows are empty, say the query returned no data and offer the most likely reason from the query's filters. Do not invent a value.
- If the result is a small set, you may list the values.
- State assumptions the query made (e.g. interpreted "top" as highest, a year filter) as short bullets.
- Output ONLY a JSON object: {{"explanation": "...", "assumptions": ["..."]}}"""

EXPLAIN_USER = """Question: {question}

SQL that ran:
{sql}

Columns: {columns}

Rows (first {shown} of {total}):
{rows}"""


def build_explain_messages(
    question: str, sql: str, columns: list[str], rows: list[tuple], shown: int = 10
) -> list[dict[str, str]]:
    user = EXPLAIN_USER.format(
        question=question,
        sql=sql,
        columns=", ".join(columns),
        rows="\n".join(repr(r) for r in rows[:shown]),
        shown=min(shown, len(rows)),
        total=len(rows),
    )
    return [
        {"role": "system", "content": EXPLAIN_SYSTEM},
        {"role": "user", "content": user},
    ]


# --- client ----------------------------------------------------------------

class GemmaClient:
    """Minimal OpenAI-compatible chat client with JSON-mode post-processing."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self.model = self.settings.gemma_model
        # Imported lazily so the stub backend and tests run without the SDK.
        from openai import OpenAI

        self._client = OpenAI(
            base_url=self.settings.gemma_base_url,
            api_key=self.settings.gemma_api_key,
            timeout=self.settings.gemma_timeout,
        )

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.1) -> str:
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
        )
        return resp.choices[0].message.content or ""


class StubGemmaClient:
    """Deterministic offline stand-in for CI and H3-H4 stub wiring.

    It never calls a network endpoint. ``responses`` maps a lowercase
    substring of the question to a canned JSON payload; anything unmatched
    returns a valid single-table lookup so the pipeline always has a shape
    to chew on. Swap in the real client by passing ``GemmaClient()`` to
    ``DataMind`` instead.
    """

    # Returned when no keyword matches and no explicit default is given:
    # declining is safer than emitting SQL for the wrong question.
    _DECLINE = {"ok": False, "reason": "unsupported", "sql": "",
                "assumptions": [], "tables": []}

    def __init__(
        self,
        responses: dict[str, dict[str, Any]] | None = None,
        default: dict[str, Any] | None = None,
        script: list[dict[str, Any]] | None = None,
    ) -> None:
        self.responses = responses or {}
        self.default = default or self._DECLINE
        # script: one payload per chat() call, in order — for retry-path tests
        # where the retry prompt still contains the old (bad) SQL text.
        self.script = list(script) if script else []
        self.model = "stub-gemma"

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.1) -> str:
        if self.script:
            return json.dumps(self.script.pop(0))
        # Explanation calls get a deterministic canned reply so the full
        # pipeline (not just SQL drafting) is exercised offline.
        if any("You explain SQL query results" in m["content"] for m in messages):
            return json.dumps({
                "explanation": (
                    "The query returned the rows shown as evidence; the "
                    "finding follows directly from them."
                ),
                "assumptions": [],
            })
        # Match against user messages only — the system prompt carries
        # schema + follow-up history whose text would otherwise shadow the
        # actual question.
        text = " ".join(
            m["content"] for m in messages if m.get("role") == "user"
        )
        lowered = text.lower()
        for needle, payload in self.responses.items():
            if needle in lowered:
                return json.dumps(payload)
        return json.dumps(self.default)


def parse_llm_json(raw: str) -> dict[str, Any]:
    """Extract the first JSON object from a model reply.

    Gemma sometimes wraps output in markdown fences or adds a stray sentence;
    we brace-scan instead of trusting the whole string to json.loads.
    """
    start = raw.find("{")
    if start == -1:
        raise ValueError(f"no JSON object found in model reply: {raw[:200]!r}")
    depth = 0
    in_str = False
    esc = False
    for i, ch in enumerate(raw[start:], start=start):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(raw[start : i + 1])
    raise ValueError(f"unterminated JSON object in model reply: {raw[:200]!r}")


def strip_sql(sql: str) -> str:
    """Remove markdown fences / trailing semicolons Gemma tends to add."""
    sql = sql.strip()
    sql = re.sub(r"^```(?:sql)?\s*", "", sql)
    sql = re.sub(r"\s*```$", "", sql)
    return sql.strip().rstrip(";").strip()
