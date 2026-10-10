import json
import pytest
from builder.generate import parse_response, make_prompt


def test_parse_response_rejects_incomplete_output():
    with pytest.raises(ValueError):
        parse_response('{"workflow":')
    with pytest.raises(ValueError):
        parse_response('{"workflow": {}, "coverage": []}')


def test_prompt_preserves_raw_brief_and_new_schema(tmp_path):
    docs=tmp_path / "docs"; docs.mkdir()
    examples=tmp_path / "examples"; examples.mkdir()
    for name in ("workflow-format.md","tools-and-code.md"):
        (docs/name).write_text("format reference")
    (examples/"base-agent.json").write_text('{}')
    inputs={"briefs":[{"path":"memo.md","text":"The memo overrides the old deadline."}],"api":{"paths":{"/verify_identity":{"field":"new_field"}}}}
    prompt=make_prompt(inputs,tmp_path)
    assert "The memo overrides the old deadline." in prompt
    assert "new_field" in prompt


def test_parse_response_accepts_fenced_json():
    data={"workflow":{"nodes":{"a":{}},"initial_node":"a"},"rules":[{"source":"memo.md:1","rule":"sample"}],"coverage":[{"rule":0,"location":"nodes.a"}]}
    assert parse_response('```json\n'+json.dumps(data)+'\n```') == data
