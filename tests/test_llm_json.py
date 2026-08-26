import json

import pytest

from zengrowth.llm_json import parse_json_strict


def test_parse_plain_json():
    assert parse_json_strict('{"a": 1}') == {"a": 1}


def test_parse_code_fenced_json():
    assert parse_json_strict('```json\n{"a": 1}\n```') == {"a": 1}


def test_recovers_json_object_wrapped_in_prose():
    text = (
        "I need to look at the experience section first. Here is the result:\n"
        '{"title": "T", "summary": "S {with braces}", "evidence_ids": ["e1"]}\n'
        "Let me know if you need anything else."
    )
    parsed = parse_json_strict(text)
    assert parsed["title"] == "T"
    assert parsed["summary"] == "S {with braces}"
    assert parsed["evidence_ids"] == ["e1"]


def test_recovers_object_when_prose_contains_stray_brace():
    text = 'Note: use {curly} carefully.\n{"ok": true}'
    assert parse_json_strict(text) == {"ok": True}


def test_raises_when_no_json_present():
    with pytest.raises(json.JSONDecodeError):
        parse_json_strict("no json here at all")
