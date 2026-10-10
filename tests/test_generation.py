import json
import pytest
from builder.generate import parse_response, make_prompt


def test_parse_response_rejects_incomplete_output():
    with pytest.raises(ValueError):
        parse_response('{"workflow":')
    with pytest.raises(ValueError):
        parse_response('{"spec": {}, "coverage": []}')


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
    data={"spec":{"language":"English"},"rules":[{"source":"memo.md:1","rule":"sample"}],"coverage":[{"rule":0,"location":"policy"}]}
    assert parse_response('```json\n'+json.dumps(data)+'\n```') == data


def test_generate_retries_malformed_output_and_compiles_best_spec(tmp_path, monkeypatch):
    import asyncio
    from pathlib import Path
    from builder import generate as gen
    from builder.runtime import Budget, Trace
    root = Path(__file__).resolve().parent.parent
    api = json.loads((root/"vendor/kit-v3/tools/openapi.json").read_text())
    spec = json.loads((root/"tests/fixtures/spec_sample.json").read_text())
    bad = dict(spec, now_variable="clock")
    good = {"rules": [{"source": "x", "rule": "y"}], "coverage": [{"rule": 0, "location": "policy"}]}
    replies = iter(["not json", json.dumps(dict(good, spec=bad)), json.dumps(dict(good, spec=bad))])
    async def fake(prompt, trace, model, cwd, purpose, budget, timeout=600):
        return next(replies)
    monkeypatch.setattr(gen, "ask_model", fake)
    trace = Trace(tmp_path/"trace.jsonl", secrets=[])
    inputs = {"briefs": [{"path": "b.md", "text": "brief"}], "api": api}
    data = asyncio.run(gen.generate(inputs, None, Budget(1800), trace, "m", tmp_path))
    events = [json.loads(line)["event"] for line in (tmp_path/"trace.jsonl").read_text().splitlines()]
    assert "model_output_rejected" in events and "spec_still_invalid" in events
    assert data["workflow"]["nodes"]["identify"]
