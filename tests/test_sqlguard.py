"""Tests for the read-only SQL guard (A, H2-H3)."""
import pytest

from datamind.sqlguard import ValidationError, classify_question, validate_sql
from datamind.stub_executor import _bare_schema

SCHEMA = _bare_schema()


def test_plain_select_passes():
    sql = "SELECT * FROM CUSTOMER LIMIT 10"
    assert validate_sql(sql, SCHEMA) == sql


def test_dml_rejected():
    for sql in [
        "DELETE FROM CUSTOMER",
        "UPDATE CUSTOMER SET C_COUNTRY = 'X'",
        "INSERT INTO CUSTOMER VALUES (1)",
        "DROP TABLE CUSTOMER",
        "TRUNCATE TABLE CUSTOMER",
        "CREATE TABLE X (a int)",
    ]:
        with pytest.raises(ValidationError, match="SELECT"):
            validate_sql(sql, SCHEMA)


def test_unknown_table_rejected():
    with pytest.raises(ValidationError, match="unknown table"):
        validate_sql("SELECT * FROM SECRETS", SCHEMA)


def test_smuggled_second_statement_rejected():
    with pytest.raises(ValidationError, match="one statement"):
        validate_sql("SELECT 1; DROP TABLE CUSTOMER", SCHEMA)


def test_cte_select_ok_but_cte_write_rejected():
    ok = "WITH t AS (SELECT * FROM CUSTOMER) SELECT * FROM t LIMIT 5"
    assert "WITH" in validate_sql(ok, SCHEMA).upper()


def test_execute_immediate_rejected():
    with pytest.raises(ValidationError, match="not allowed"):
        validate_sql(
            "SELECT EXECUTE_IMMEDIATE('DROP TABLE CUSTOMER') FROM CUSTOMER", SCHEMA
        )


def test_garbage_rejected():
    with pytest.raises(ValidationError, match="parse"):
        validate_sql("SELECT FROM WHERE", SCHEMA)


def test_classify_question():
    assert classify_question("top 5 customers by spend") == "ranking"
    assert classify_question("sales by year trend") == "time-series"
    assert classify_question("how many items are there") == "aggregate"
    assert classify_question("which countries appear") == "lookup"
    assert classify_question("hello") == "general"
