import json
import pytest
from builder.runtime import Budget, Trace, load_inputs, validate_workflow, select_candidate


def test_budget_reserves_finalization():
    now = [100.0]
    budget = Budget(180, reserve=30, clock=lambda: now[0])
    now[0] = 240
    assert budget.available() == 10
    with pytest.raises(TimeoutError):
        budget.require(11)
    assert budget.remaining() == 40


def test_trace_redacts_values_even_in_nested_errors(tmp_path):
    trace = Trace(tmp_path / "trace.jsonl", secrets=["private-key-value"])
    trace.emit("error", detail={"nested": ["Bearer private-key-value"]})
    content = trace.path.read_text()
    assert "private-key-value" not in content
    assert json.loads(content)["detail"]["nested"] == ["Bearer [REDACTED]"]


def test_load_inputs_uses_supplied_api_and_all_briefs(tmp_path):
    a, b, api = [tmp_path / n for n in ("a.md", "b.md", "bank.json")]
    a.write_text("old rule"); b.write_text("memo overrides old rule")
    api.write_text(json.dumps({"openapi":"3.0.3", "servers":[{"url":"https://bank.invalid/v9"}],"paths":{}}))
    result = load_inputs([a,b],api)
    assert [d["text"] for d in result["briefs"]] == ["old rule","memo overrides old rule"]
    assert result["api"]["servers"][0]["url"] == "https://bank.invalid/v9"
    old_hash = result["fingerprint"]
    b.write_text("changed memo")
    assert load_inputs([a,b],api)["fingerprint"] != old_hash


def test_validator_catches_broken_routes_and_forbidden_http():
    workflow = {"initial_node":"start", "nodes":{"start":{"node_type":"conversation","transitions":[{"target_node":"missing"}],"tools":[{"function":{"handler":"__function__:api_call","parameters":{"properties":{"url":{"default":"https://wrong.invalid/x"}}}}}]}}}
    issues = validate_workflow(workflow,{"servers":[{"url":"https://bank.invalid/v1"}],"paths":{}})
    assert any("missing" in x for x in issues)
    assert any("URL" in x for x in issues)


def test_validator_rejects_invalid_python():
    workflow = {"initial_node":"start","nodes":{"start":{"pre_actions":[{"function":{"handler":"__function__:code_exec","parameters":{"properties":{"code":{"default":"if broken"}}}}}]}}}
    assert any("Python" in x for x in validate_workflow(workflow,{"servers":[],"paths":{}}))


def test_candidate_selection_does_not_trade_known_passes_for_regressions():
    old={"suite":"same","status":"completed","case_passes":{"a":True,"b":False}}
    new={"suite":"same","status":"completed","case_passes":{"a":False,"b":True}}
    assert select_candidate(old,new) == "incumbent"
    new["case_passes"]["a"]=True
    assert select_candidate(old,new) == "challenger"
    new["suite"]="different"
    assert select_candidate(old,new) == "incumbent"
