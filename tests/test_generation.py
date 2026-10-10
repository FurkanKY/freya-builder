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


def test_choose_read_keeps_the_read_the_others_agree_with():
    from builder.generate import choose_read
    base = {"call_variables": ["first_name", "today"], "calendar": {"closed_day_rule": "none"}, "policy": {"a": "one wording"},
            "outcomes": {"no_reason": ["A", "B", "C"]}}
    odd = json.loads(json.dumps(base)); odd["call_variables"].append("customer_id"); odd["outcomes"]["no_reason"] = ["A"]
    other = json.loads(json.dumps(base)); other["policy"] = {"a": "another wording"}
    pick, scores, split = choose_read([odd, base, other])
    # Free-text fields carry no vote; the two reads that agree beat the odd one, the earliest of them wins.
    assert pick == 1 and scores[0] < scores[1] == scores[2]
    assert split == ["call_variables", "outcomes.no_reason"]


def test_generate_consensus_survives_failed_and_late_reads(tmp_path, monkeypatch):
    import asyncio
    import builder.generate as g
    from builder.runtime import Budget, Trace

    async def fake(inputs, kit, budget, trace, model, cwd, previous=None, feedback=None, label=""):
        n = label.split()[1]
        if n == "1":
            raise RuntimeError("model failed")
        if n == "3":
            await asyncio.sleep(30)
        return {"spec": {"call_variables": ["x", n]}, "workflow": {}}

    monkeypatch.setattr(g, "generate", fake)
    monkeypatch.setattr(g, "_checked", lambda data, inputs: [])
    trace = Trace(tmp_path/"trace.jsonl")
    data = asyncio.run(g.generate_consensus({}, None, Budget(1800), trace, "m", tmp_path, reads=3, grace=0.2))
    assert data["spec"]["call_variables"] == ["x", "2"]
    vote = [json.loads(l) for l in (tmp_path/"trace.jsonl").read_text().splitlines() if '"spec_vote"' in l][0]
    assert vote["succeeded"] == [2] and vote["chosen"] == 2 and len(vote["failed"]) == 2
    # A read the compiler cannot build never wins over a clean one.
    async def two(inputs, kit, budget, trace, model, cwd, previous=None, feedback=None, label=""):
        return {"spec": {"v": label.split()[1]}, "workflow": {}}
    monkeypatch.setattr(g, "generate", two)
    monkeypatch.setattr(g, "_checked", lambda data, inputs: [g.COMPILE_FAILED + ": x"] if data["spec"]["v"] == "1" else [])
    data = asyncio.run(g.generate_consensus({}, None, Budget(1800), trace, "m", tmp_path, reads=2))
    assert data["spec"]["v"] == "2"


def test_choose_read_votes_on_meaning_not_wording_or_order():
    from builder.generate import choose_read
    base = {"call_variables": ["first_name", "today"], "opening_line": "Hello {{first_name}}, this is the bank.",
            "calendar": {"closed_day_rule": "previous_business_day", "holidays": [{"date": "2026-12-25", "name": "Christmas"},
                                                                                {"date": "2026-12-26", "name": "Boxing Day"}]},
            "identity": {"questions": [{"field": "dob", "ask": "Ask the date of birth.", "answer_format": "YYYY-MM-DD"}]},
            "outcomes": {"no_reason": ["A", "B", "C"]},
            "account": {"bands": [{"min": 1, "max": 30, "name": "early", "attempt_plan": ["full", "floor"]},
                                  {"min": 31, "max": 90, "name": "late", "attempt_plan": ["full"]}],
                        "spoken_name_by_type": {"loan": "loan ending <ref>"}}}
    copy = lambda: json.loads(json.dumps(base))
    misread = copy(); misread["calendar"]["closed_day_rule"] = "none"
    # The two good reads differ from each other only in wording and in the order of order-free lists.
    worded = copy(); worded["opening_line"] = "Hi {{first_name}}, the bank calling."; worded["call_variables"].reverse()
    worded["calendar"]["holidays"].reverse(); worded["calendar"]["holidays"][0]["name"] = "Boxing day"
    worded["account"]["bands"].reverse(); worded["account"]["bands"][0]["name"] = "31 to 90 days"
    other = copy(); other["identity"]["questions"][0]["ask"] = "Ask for the date of birth."
    other["outcomes"]["no_reason"] = ["C", "A", "B"]; other["account"]["spoken_name_by_type"]["loan"] = "your loan ending <ref>"
    pick, scores, split = choose_read([misread, worded, other])
    assert pick == 1 and scores[0] < scores[1] == scores[2]
    assert split == ["calendar.closed_day_rule"]
    # What the compiler takes from a wording field still votes: a dropped variable in the opening line.
    novar = copy(); novar["opening_line"] = "Hello, this is the bank."
    assert choose_read([novar, worded, other])[0] == 1
    # A read that may not win (more contract errors) still votes for the read it agrees with.
    assert choose_read([copy(), misread, copy()], eligible=[1, 2])[0] == 2


def test_generate_consensus_waits_for_a_first_read_as_long_as_the_budget_allows(tmp_path, monkeypatch):
    import asyncio
    import builder.generate as g
    from builder.runtime import Budget, Trace

    async def slow(inputs, kit, budget, trace, model, cwd, previous=None, feedback=None, label=""):
        await asyncio.sleep(1.5)
        return {"spec": {"v": label.split()[1]}, "workflow": {}}

    monkeypatch.setattr(g, "generate", slow)
    monkeypatch.setattr(g, "_checked", lambda data, inputs: [])
    # Less than 420 s left to publish: the reads still get the time generate() itself would use.
    data = asyncio.run(g.generate_consensus({}, None, Budget(500), Trace(tmp_path/"trace.jsonl"), "m", tmp_path, reads=3))
    assert data["spec"]["v"] == "1"


def test_reads_wanted_falls_back_to_three():
    from builder.build import reads_wanted
    assert [reads_wanted(v) for v in (None, "", "x", "0", "2", " 4 ", "9")] == [3, 3, 3, 1, 2, 4, 5]
