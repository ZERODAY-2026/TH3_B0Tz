"""Tests for the local Gemma client (JSON extraction, retries, health)."""
import json

import pytest

from legallens.llm import StubGemma, extract_json, generate_json, health_check


def test_extract_json_plain():
    assert extract_json('{"ok": true}') == {"ok": True}


def test_extract_json_fenced():
    raw = '```json\n{"ok": true, "sql": "SELECT 1"}\n```'
    assert extract_json(raw)["sql"] == "SELECT 1"


def test_extract_json_chatty():
    raw = 'Sure! Here you go: {"a": {"b": [1, 2]}} hope that helps'
    assert extract_json(raw)["a"]["b"] == [1, 2]


def test_extract_json_array():
    assert extract_json('[{"kind": "obligation"}]') == [{"kind": "obligation"}]


def test_extract_json_no_json_raises():
    with pytest.raises(ValueError):
        extract_json("no json here at all")


def test_generate_json_retries_then_succeeds():
    # First reply is chatty garbage, second is valid after the retry hint.
    stub = StubGemma(script=[
        "Sure, here is what you asked for!",
        '{"ok": true}',
    ])
    out = generate_json("return json", client=stub)
    assert out == {"ok": True}
    assert "RETRY" in stub.calls[1]


def test_generate_json_schema_check_drives_retry():
    stub = StubGemma(script=[
        '{"kind": "banana"}',                 # invalid kind
        '{"kind": "obligation", "plain_text": "x", "quote": "y", "passage_id": "p1.c1", "label": "STATED"}',
    ])
    from legallens.llm import _validate_findings_payload
    out = generate_json("return findings", client=stub,
                        schema_check=_validate_findings_payload)
    assert out["kind"] == "obligation"


def test_generate_json_gives_up_after_max_retries():
    stub = StubGemma(script=["garbage"] * 4)
    with pytest.raises(ValueError, match="no valid JSON"):
        generate_json("return json", client=stub)


def test_health_check_no_server():
    assert health_check() is False  # nothing on 127.0.0.1:8080 in CI
