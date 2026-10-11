import json

from builder.case import parse_object
from builder.jsonfix import loads_object


def _contract(drop_after=None):
    api = {"openapi": "3.0.0", "info": {"title": "t", "version": "1"}, "servers": [{"url": "https://x.example/v1"}],
           "paths": {f"/op{i}": {"post": {"operationId": f"op{i}", "requestBody": {"content": {"application/json": {
               "schema": {"type": "object", "properties": {"data": {"type": "object", "properties": {"a": {"type": "string"}}}}}}}},
               "responses": {"200": {"description": "ok"}, "500": {"description": "error"}}}} for i in range(4)}}
    data = {"documents": [{"path": "a.md", "role": "brief"}], "openapi": api, "roles": {"get_account": "POST /op1"},
            "call_kind": "inbound_service", "notes": "n"}
    text = json.dumps(data, indent=1)
    if drop_after:
        # Drop the closing bracket of the object that ends right before drop_after's key.
        at = text.index(drop_after)
        cut = text.rindex("}", 0, at)
        text = text[:cut] + text[cut + 1:]
    return data, text


def test_a_model_answer_that_dropped_a_closing_bracket_mid_answer_is_read_with_its_intended_structure():
    data, text = _contract(drop_after='"/op2"')
    try:
        json.loads(text)
        raise AssertionError("the test text should not parse")
    except json.JSONDecodeError:
        pass
    assert parse_object(text) == data


def test_a_fenced_answer_with_a_trailing_comma_and_an_unclosed_end_parses():
    assert loads_object('```json\n{"a": {"b": [1, 2,], "c": "x"\n```') == {"a": {"b": [1, 2], "c": "x"}}
    assert loads_object('{"a": 1, "b": "cut off') == {"a": 1, "b": "cut off"}
