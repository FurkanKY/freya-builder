import json
from pathlib import Path
from builder.compile import compile_workflow
from builder.generate import validate_spec
from builder.runtime import validate_workflow
from builder.spec import normalize_spec, resolve_refs, weekdays

ROOT = Path(__file__).resolve().parent.parent
API = json.loads((ROOT/"vendor/kit-v3/tools/openapi.json").read_text())
SPEC = json.loads((ROOT/"tests/fixtures/spec_sample.json").read_text())
BRIEFS = [{"path": "b.md", "text": "brief"}]


def tool(wf, node, name):
    return next(t for t in wf["nodes"][node]["tools"] if t["function"]["name"] == name)


def run_hook(code, data):
    result = {"data": data}
    exec(code, {"result": result})
    return result["data"]["what_to_do_next"]


def test_model_type_deviations_compile_instead_of_crashing():
    spec = json.loads(json.dumps(SPEC))
    spec["policy"] = {"before_verification": ["1. open", "2. ask"], "closing": {"promise": "a promise was made"}, "precedence": ["memo wins"]}
    spec["account"]["floor_field_by_type"] = "minimum_payment"
    spec["account"]["spoken_name_by_type"] = "your account"
    spec["identity"]["questions"] = ["date_of_birth", "phone_last4"]
    spec["outcomes"] = ["promise", "paid"]
    spec["tool_field_hints"] = {"create_promise": "a business day"}
    spec["call_variables"] = [{"name": "customer_id"}, {"name": "now"}, {"name": "first_name"}]
    spec["calendar"]["business_weekdays"] = "Monday to Friday"
    wf = compile_workflow(spec, API, BRIEFS)
    assert validate_workflow(wf, API) == []
    assert "memo wins" in wf["system_prompt"] and "promise: a promise was made" in wf["system_prompt"]
    assert isinstance(validate_spec(spec, API), list)


def test_weekday_names_are_normalised():
    assert weekdays("Monday to Friday") == ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    assert weekdays(["mon", "Tue", "WEDNESDAY"]) == ["Monday", "Tuesday", "Wednesday"]


def test_ref_request_bodies_are_resolved():
    api = json.loads(json.dumps(API))
    path = next(p for p in api["paths"] if p.endswith("create_promise"))
    content = api["paths"][path]["post"]["requestBody"]["content"]["application/json"]
    api.setdefault("components", {}).setdefault("schemas", {})["Promise"] = content["schema"]
    content["schema"] = {"$ref": "#/components/schemas/Promise"}
    wf = compile_workflow(SPEC, api, BRIEFS)
    body = tool(wf, "negotiate", "create_promise")["function"]["parameters"]["properties"]["body"]["properties"]
    assert body["customer_id"]["default"] == "{{customer_id}}" and "amount" in body
    assert resolve_refs(api)["paths"][path]["post"]["requestBody"]["content"]["application/json"]["schema"]["properties"]


def test_hooks_follow_the_banks_own_flags():
    spec = json.loads(json.dumps(SPEC))
    spec["identity"]["complete_flag"] = "result.identity_confirmed"
    spec["identity"]["answer_flag"] = "correct"
    wf = compile_workflow(spec, API, BRIEFS)
    hook = tool(wf, "identify", "verify_identity")["post_process_code"]
    assert "correct" in run_hook(hook, {"ok": True, "correct": True, "result": {"identity_confirmed": False}})
    assert "fully verified" in run_hook(hook, {"ok": True, "correct": True, "result": {"identity_confirmed": True}})
    promise = tool(wf, "negotiate", "create_promise")["post_process_code"]
    assert "IS recorded" in run_hook(promise, {"success": True})
    assert "IS recorded" in run_hook(promise, {"promise_id": "x"})
    assert "NOT recorded" in run_hook(promise, {"error": "down"})


def test_identity_answers_named_like_call_variables_are_not_baked():
    api = json.loads(json.dumps(API))
    path = next(p for p in api["paths"] if p.endswith("verify_identity"))
    api["paths"][path]["post"]["requestBody"]["content"]["application/json"]["schema"]["properties"]["last_name"] = {"type": "string"}
    wf = compile_workflow(SPEC, api, BRIEFS)
    body = tool(wf, "identify", "verify_identity")["function"]["parameters"]["properties"]["body"]["properties"]
    assert body["last_name"]["default"] != "{{last_name}}"
    assert body["customer_id"]["default"] == "{{customer_id}}"


def test_tool_method_follows_the_api():
    api = json.loads(json.dumps(API))
    path = next(p for p in api["paths"] if p.endswith("get_account"))
    api["paths"][path] = {"get": api["paths"][path]["post"]}
    wf = compile_workflow(SPEC, api, BRIEFS)
    get = wf["nodes"]["load_account"]["pre_actions"][0]["function"]["parameters"]["properties"]["method"]["default"]
    assert get == "GET"
    assert not [e for e in validate_workflow(wf, api) if "method" in e]


def test_normalise_is_idempotent_and_keeps_single_brace_names_speakable():
    spec = json.loads(json.dumps(SPEC))
    spec["opening_line"] = "May I speak to {first_name}?"
    once = normalize_spec(spec, API)
    assert "{{first_name}}" in once["opening_line"]
    assert normalize_spec(once, API) == once


def test_clock_variable_is_added_only_when_no_call_variable_holds_the_time():
    spec = json.loads(json.dumps(SPEC))
    spec["call_variables"], spec["now_variable"] = ["first_name", "customer_id"], "now"
    assert "now" in normalize_spec(spec, API)["call_variables"]
    spec["call_variables"] = ["first_name", "call_time"]
    assert "now" not in normalize_spec(spec, API)["call_variables"]
