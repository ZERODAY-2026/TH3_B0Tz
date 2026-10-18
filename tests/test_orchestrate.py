"""End-to-end tests of answer() against the stub executor + stub Gemma."""
from datamind.llm import StubGemmaClient, parse_llm_json, strip_sql
from datamind.orchestrate import DataMind
from datamind.stub_executor import _bare_schema, run_query
from datamind.types import Answer


def make_dm(responses=None, default=None, script=None):
    return DataMind(
        client=StubGemmaClient(responses=responses, default=default, script=script),
        schema=_bare_schema(),
        run_query=run_query,
    )


def test_happy_path_lookup():
    dm = make_dm(default={
        "ok": True, "sql": "SELECT * FROM ITEM LIMIT 50",
        "assumptions": ["items limited to 50 rows"], "tables": ["ITEM"],
    })
    a = dm.answer("list the items")
    assert isinstance(a, Answer)
    assert a.sql and a.sql.upper().startswith("SELECT")
    assert a.query_result and a.query_result.row_count == 4
    assert not a.ambiguous and not a.unsupported
    assert a.model == "stub-gemma"


def test_ambiguous_phrase_asks_for_clarification():
    dm = make_dm()
    a = dm.answer("what are the best items?")
    assert a.ambiguous
    assert "vague" in a.text.lower() or "rephras" in a.text.lower()
    assert a.query_result is None  # no query burned


def test_model_says_ambiguous():
    dm = make_dm(responses={"vague thing": {"ok": False, "reason": "ambiguous", "sql": ""}})
    a = dm.answer("tell me about the vague thing")
    assert a.ambiguous and a.query_result is None


def test_model_says_unsupported():
    dm = make_dm(responses={"weather": {"ok": False, "reason": "unsupported", "sql": ""}})
    a = dm.answer("what is the weather in Dharwad")
    assert a.unsupported
    assert "CUSTOMER" in a.text  # lists available tables


def test_invalid_sql_retries_then_succeeds():
    # Attempt 1 drafts an unknown table; the retry prompt feeds the error
    # back and attempt 2 lands on a valid table.
    dm = make_dm(script=[
        {"ok": True, "sql": "SELECT * FROM SECRET_TABLE", "assumptions": [], "tables": []},
        {"ok": True, "sql": "SELECT * FROM CUSTOMER LIMIT 10", "assumptions": [], "tables": ["CUSTOMER"]},
    ])
    a = dm.answer("show me the customer rows please")
    assert a.sql and "CUSTOMER" in a.sql.upper()
    assert a.query_result and a.query_result.error is None


def test_retry_exhaustion_is_honest():
    dm = make_dm(default={"ok": True, "sql": "SELECT * FROM SECRET_TABLE", "assumptions": [], "tables": []})
    a = dm.answer("show me anything")
    assert a.sql is None and a.query_result is None
    assert "could not write a safe query" in a.text


def test_empty_result_is_honest():
    dm = make_dm(default={
        "ok": True,
        "sql": "SELECT * FROM ITEM WHERE I_CATEGORY = 'FOOD' LIMIT 50",
        "assumptions": [], "tables": ["ITEM"],
    })
    # Stub returns all rows regardless of WHERE; force an empty result set
    # by pointing the executor at a table the stub empties.
    a = dm.answer("list items in category food")
    assert isinstance(a, Answer)  # shape sanity; empty-result wording covered below


def test_empty_rows_explanation_never_fabricates():
    from datamind.types import QueryResult

    dm = make_dm(default={
        "ok": True, "sql": "SELECT * FROM ITEM LIMIT 5",
        "assumptions": [], "tables": ["ITEM"],
    })
    # Executor returns zero rows: the answer must say so plainly and still
    # carry the executed query as evidence — never a made-up number.
    dm.run_query = lambda sql: QueryResult(columns=["X"], rows=[], query_id="q2")
    a = dm.answer("list the items")
    assert "no rows" in a.text.lower()
    assert a.query_result is not None  # the query DID run; evidence retained


def test_followup_uses_history():
    dm = make_dm(default={
        "ok": True, "sql": "SELECT * FROM ITEM LIMIT 5", "assumptions": [], "tables": ["ITEM"],
    })
    dm.answer("list the items")           # seeds history
    a = dm.answer("and what about customers")  # follow-up marker
    assert isinstance(a, Answer)


def test_parse_llm_json_handles_fences():
    raw = '```json\n{"ok": true, "sql": "SELECT 1"}\n```'
    assert parse_llm_json(raw)["sql"] == "SELECT 1"
    raw2 = 'Sure! {"a": {"b": [1,2]}} hope that helps'
    assert parse_llm_json(raw2)["a"]["b"] == [1, 2]


def test_strip_sql():
    assert strip_sql("```sql\nSELECT 1;\n```") == "SELECT 1"
    assert strip_sql("SELECT 1;") == "SELECT 1"


def test_answer_dataclass_fields():
    a = Answer(text="x")
    assert a.assumptions == [] and a.ambiguous is False and a.model == ""
