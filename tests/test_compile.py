import json
from pathlib import Path
from builder.compile import compile_workflow
from builder.generate import validate_spec
from builder.runtime import validate_workflow

ROOT = Path(__file__).resolve().parent.parent
API = json.loads((ROOT/"vendor/kit-v3/tools/openapi.json").read_text())
SPEC = json.loads((ROOT/"tests/fixtures/spec_sample.json").read_text())
BRIEFS = [{"path": "memo.md", "text": "The memo overrides the old deadline."}]


def run_facts(workflow, variables):
    code = workflow["nodes"]["account_facts"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
    exec(compile(code, "facts", "exec"), {"vars": variables})
    return variables


def test_compiled_workflow_passes_local_validation_and_keeps_raw_brief():
    wf = compile_workflow(SPEC, API, BRIEFS)
    assert validate_workflow(wf, API) == []
    assert "The memo overrides the old deadline." in wf["system_prompt"]
    assert "agent_config" not in wf


def test_identity_gates_account_lookup():
    wf = compile_workflow(SPEC, API, BRIEFS)
    identify = wf["nodes"]["identify"]
    assert "get_account" not in [t["function"]["name"] for t in identify["tools"]]
    assert identify["transitions"][0]["target_node"] == "load_account"
    assert "all_verified" in json.dumps(identify["transitions"][0]["condition"])


def test_call_variables_are_baked_and_other_fields_are_model_filled():
    wf = compile_workflow(SPEC, API, BRIEFS)
    tool = next(t for t in wf["nodes"]["negotiate"]["tools"] if t["function"]["name"] == "create_promise")
    body = tool["function"]["parameters"]["properties"]["body"]
    assert body["properties"]["customer_id"]["default"] == "{{customer_id}}"
    assert body["properties"]["date"]["default"] == "{{date}}"
    assert "customer_id" not in body["required"]


def test_close_call_drops_reason_for_reasonless_outcomes():
    wf = compile_workflow(SPEC, API, BRIEFS)
    tool = next(t for t in wf["nodes"]["negotiate"]["tools"] if t["function"]["name"] == "close_call")
    for outcome, reason, kept in (("promise", "x", False), ("no_promise", "refused", True), ("no_promise", "{{close_call_reason}}", False)):
        config = {"body": {"outcome": outcome, "reason": reason}}
        exec(tool["pre_process_code"], {"config": config})
        assert ("reason" in config["body"]) == kept


def test_facts_compute_deadline_from_spec_and_skip_holiday():
    wf = compile_workflow(SPEC, API, BRIEFS)
    products = [{"product_id": "p1", "type": "credit_card", "card_last4": "1234", "past_due": 300.0, "days_late": 4, "minimum_payment": 90.0}]
    out = run_facts(wf, {"now": "2026-10-21T09:00", "account_products": json.dumps(products)})
    # 5 business days after Wed 21 Oct, skipping the weekend and the 26 Oct holiday: 22, 23, 27, 28, 29.
    assert "deadline 2026-10-29" in out["account_facts"]
    assert "credit card ending 1234" in out["account_facts"]
    assert "2026-10-26 Monday: HOLIDAY (bank holiday), NOT a business day; previous business day 2026-10-23 Friday; next business day 2026-10-27 Tuesday; on or before the deadline of p1" in out["date_facts"]
    assert out["facts_state"] == "ready"


def test_facts_never_raise_on_bad_input():
    wf = compile_workflow(SPEC, API, BRIEFS)
    out = run_facts(wf, {"now": "garbage"})
    assert out["facts_state"] == "no_date" and out["date_facts"]


def test_spec_validation_rejects_fields_outside_the_api():
    bad = json.loads(json.dumps(SPEC))
    bad["identity"]["questions"][0]["field"] = "mothers_maiden_name"
    bad["account"]["amount_field"] = "balance"
    bad["opening_line"] = "Hello {{nickname}}"
    issues = validate_spec(bad, API)
    assert any("mothers_maiden_name" in i for i in issues)
    assert any("balance" in i for i in issues)
    assert any("nickname" in i for i in issues)


def test_facts_read_the_spec_named_clock_variable():
    spec = json.loads(json.dumps(SPEC)); spec["now_variable"] = "call_time"; spec["call_variables"].append("call_time")
    wf = compile_workflow(spec, API, BRIEFS)
    out = run_facts(wf, {"call_time": "2026-10-21T09:00", "now": "1999-01-01T00:00"})
    assert out["date_facts"].startswith("Now: 2026-10-21")


def test_facts_render_attempt_plan_per_product():
    spec = json.loads(json.dumps(SPEC))
    spec["account"]["bands"][0]["attempt_plan"] = ["attempt 1: <amount> by <last_business_day_this_week>", "attempt 2: <floor> on <deadline>"]
    wf = compile_workflow(spec, API, BRIEFS)
    products = [{"product_id": "p1", "type": "credit_card", "card_last4": "1234", "past_due": 300.0, "days_late": 4, "minimum_payment": 90.0}]
    out = run_facts(wf, {"now": "2026-10-21T09:00", "account_products": json.dumps(products)})
    assert "attempt 1: 300 by 2026-10-23 (Friday" in out["account_facts"]
    assert "attempt 2: 90 on 2026-10-29 (Thursday" in out["account_facts"]


def test_tool_keys_given_as_api_paths_still_reach_the_tools():
    spec = json.loads(json.dumps(SPEC))
    spec["tool_descriptions"] = {"/v1/create_promise": "Call after a clear yes."}
    spec["tool_field_hints"] = {"/create_promise": {"date": "a business day"}}
    wf = compile_workflow(spec, API, BRIEFS)
    tool = next(t for t in wf["nodes"]["negotiate"]["tools"] if t["function"]["name"] == "create_promise")
    assert tool["function"]["description"] == "Call after a clear yes."
    assert tool["function"]["parameters"]["properties"]["body"]["properties"]["date"]["description"].startswith("a business day")
