import datetime
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
    # An HTTP failure is never reported as recorded, whatever shape the body has.
    for envelope in ({"status": "error", "status_code": 500, "data": "<html>bad gateway</html>"},
                     {"status": "success", "status_code": 503, "data": None},
                     {"status": "error", "message": "timeout", "data": {}}):
        exec(promise, {"result": envelope})
        assert "NOT recorded" in envelope["data"]["what_to_do_next"]
    ok = {"status": "success", "status_code": 200, "data": {"ok": True}}
    exec(promise, {"result": ok})
    assert "IS recorded" in ok["data"]["what_to_do_next"]


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


def _facts(spec, products):
    wf = compile_workflow(spec, API, BRIEFS)
    code = wf["nodes"]["account_facts"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
    variables = {"now": "2026-10-21T09:00", "account_products": json.dumps(products)}
    exec(compile(code, "facts", "exec"), {"vars": variables})
    return variables["account_facts"]


def test_floor_can_be_a_percentage_a_fixed_amount_or_a_field():
    product = {"product_id": "p1", "type": "credit_card", "card_last4": "1234", "past_due": 2125.1, "days_late": 4, "minimum_payment": 90.0}
    spec = json.loads(json.dumps(SPEC))
    spec["account"]["floor_field_by_type"] = {"credit_card": "25%"}
    assert "floor (25% of past_due) 531.28" in _facts(spec, [product])
    assert validate_spec(spec, API) == []
    spec["account"]["floor_field_by_type"] = {"credit_card": 50}
    assert "floor (fixed amount) 50" in _facts(spec, [product])
    assert validate_spec(spec, API) == []
    spec["account"]["floor_field_by_type"] = {"credit_card": "minimum_payment"}
    assert "floor (minimum_payment) 90" in _facts(spec, [product])
    spec["account"]["floor_field_by_type"] = {"credit_card": "10% of nonsense"}
    assert any("floor" in i for i in validate_spec(spec, API))
    # "50, or 5% of the amount owed if that is more", and the smaller of two.
    spec["account"]["floor_field_by_type"] = {"credit_card": "max(50, 5%)"}
    assert "floor (max(50, 5%)) 106.26" in _facts(spec, [product])
    assert validate_spec(spec, API) == []
    spec["account"]["floor_field_by_type"] = {"credit_card": "min(minimum_payment, 10% of past_due)"}
    assert "floor (min(minimum_payment, 10% of past_due)) 90" in _facts(spec, [product])
    assert validate_spec(spec, API) == []
    spec["account"]["floor_field_by_type"] = {"credit_card": "max(50, 5% of nonsense)"}
    assert any("floor" in i for i in validate_spec(spec, API))
    # A fixed minimum on a small debt is the whole debt.
    small = dict(product, past_due=30.0)
    spec["account"]["floor_field_by_type"] = {"credit_card": "max(50, 5%)"}
    assert "floor (max(50, 5%), at most the amount owed) 30" in _facts(spec, [small])


def test_clock_formats_and_operation_ids():
    product = {"product_id": "p1", "type": "credit_card", "card_last4": "1234", "past_due": 300.0, "days_late": 4, "minimum_payment": 90.0}
    wf = compile_workflow(SPEC, API, BRIEFS)
    code = wf["nodes"]["prepare"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
    for raw in ("2026-10-21T09:00", "2026-10-21 09:00:00Z", "2026-10-21T09:00:00+02:00", "21/10/2026 09:00", "21.10.2026", "2026/10/21"):
        variables = {"now": raw, "account_products": json.dumps([product])}
        exec(compile(code, "facts", "exec"), {"vars": variables})
        assert variables["date_facts"].startswith("Now: 2026-10-21"), raw
    api = json.loads(json.dumps(API))
    api["paths"] = {"/v2/" + p.strip("/").replace("_", "-"): {m: dict(op, operationId=p.strip("/").split("/")[-1]) for m, op in v.items()} for p, v in api["paths"].items()}
    renamed = compile_workflow(SPEC, api, BRIEFS)
    assert validate_workflow(renamed, api) == []


def test_identity_completion_can_be_a_status_value_and_a_missing_answer_flag_is_neutral():
    api = json.loads(json.dumps(API))
    path = next(p for p in api["paths"] if p.endswith("verify_identity"))
    schema = api["paths"][path]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
    schema["properties"] = {"ok": {"type": "boolean"}, "status": {"type": "string", "enum": ["pending", "verified", "failed"]}, "correct": {"type": "boolean"}}
    spec = json.loads(json.dumps(SPEC))
    spec["identity"].update({"complete_flag": "status", "answer_flag": "correct"})
    spec["identity"].pop("complete_value", None)
    assert any("complete_value" in i for i in validate_spec(spec, api))
    spec["identity"]["complete_value"] = "verified"
    assert not [i for i in validate_spec(spec, api) if "identity" in i]
    wf = compile_workflow(spec, api, BRIEFS)
    gate = wf["nodes"]["identify"]["transitions"][0]["condition"]["conditions"]
    assert {"variable": "verify_identity_response.data.status", "operator": "equals", "operand": "verified"} in gate
    hook = tool(wf, "identify", "verify_identity")["post_process_code"]
    assert "fully verified" in run_hook(hook, {"ok": True, "status": "verified", "correct": True})
    assert "This answer is correct" in run_hook(hook, {"ok": True, "status": "pending", "correct": True})
    assert "did not say" in run_hook(hook, {"ok": True, "status": "pending"})


def test_closed_day_rule_is_normalized_to_a_known_action():
    for raw, want in (("next_business_day", "next_business_day"), ("Offer the previous working day", "previous_business_day"),
                      ("ask the customer for another day", "ask_again"), (None, "none"), ("", "none")):
        spec = json.loads(json.dumps(SPEC))
        spec["calendar"]["closed_day_rule"] = raw
        assert normalize_spec(spec, API)["calendar"]["closed_day_rule"] == want


def test_last_working_day_of_the_month_is_a_business_day():
    spec = json.loads(json.dumps(SPEC))
    spec["account"]["bands"][0]["deadline"] = {"type": "last_working_day_of_month", "count": 0, "date": ""}
    assert normalize_spec(spec, API)["account"]["bands"][0]["deadline"]["type"] == "last_business_day_of_month"
    wf = compile_workflow(spec, API, BRIEFS)
    code = wf["nodes"]["prepare"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
    scope = {"vars": {"now": "2026-10-14T11:00"}}
    exec(compile(code, "facts", "exec"), scope)
    today, rule = datetime.date(2026, 10, 14), {"type": "last_business_day_of_month"}
    # 31 October 2026 is a Saturday: a working day only when the bank works on Saturdays.
    assert scope["_deadline"](rule, today, set(range(5)), {}) == datetime.date(2026, 10, 30)
    assert scope["_deadline"](rule, today, set(range(6)), {}) == datetime.date(2026, 10, 31)
    assert scope["_deadline"](rule, today, set(range(5)), {"2026-10-30": "x"}) == datetime.date(2026, 10, 29)
    # The month's last calendar day is a Saturday: a promise date is a business day, so the deadline is the Friday before it.
    assert scope["_deadline"]({"type": "end_of_month"}, today, set(range(5)), {}) == datetime.date(2026, 10, 30)
    assert scope["_deadline"]({"type": "end_of_month"}, today, set(range(6)), {}) == datetime.date(2026, 10, 31)
    nov30 = datetime.date(2026, 11, 30)
    assert scope["_deadline"]({"type": "end_of_next_month"}, today, set(range(5)), {}) == nov30
    assert scope["_deadline"]({"type": "end_of_next_month"}, datetime.date(2026, 12, 3), set(range(7)), {}) == datetime.date(2027, 1, 31)
    assert scope["_deadline"]({"type": "last_business_day_of_next_month"}, today, set(range(5)), {"2026-11-30": "x"}) == datetime.date(2026, 11, 27)
    # Wednesday 14 October: Friday 16th, then Friday 23rd; on Saturday 17th this week's last business day has passed.
    week = {"type": "last_business_day_this_week"}
    assert scope["_deadline"](week, today, set(range(5)), {}) == datetime.date(2026, 10, 16)
    assert scope["_deadline"](week, datetime.date(2026, 10, 17), set(range(5)), {}) == datetime.date(2026, 10, 23)
    assert scope["_deadline"]({"type": "last_business_day_next_week"}, today, set(range(5)), {}) == datetime.date(2026, 10, 23)
    # This or next month's end and this or next week's last business day map to their kinds; a count, "after" or "within"
    # stays unknown ("see policy").
    for kind, want in [("month_end", "end_of_month"), ("end-of-month", "end_of_month"), ("end_of_next_month", "end_of_next_month"),
                       ("end of the following month", "end_of_next_month"),
                       ("last working day of next month", "last_business_day_of_next_month"),
                       ("end_of_week", "last_business_day_this_week"), ("last business day of next week", "last_business_day_next_week"),
                       ("within a week", "within a week"), ("end of 2 weeks", "end of 2 weeks"),
                       ("calendar_month", "calendar_month"), ("months_after_today", "months_after_today")]:
        spec["account"]["bands"][0]["deadline"] = {"type": kind, "count": 1, "date": ""}
        assert normalize_spec(spec, API)["account"]["bands"][0]["deadline"]["type"] == want, kind


def test_a_word_valued_answer_result_and_a_numeric_completion_value():
    api = json.loads(json.dumps(API))
    path = next(p for p in api["paths"] if p.endswith("verify_identity"))
    schema = api["paths"][path]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
    schema["properties"] = {"ok": {"type": "boolean"}, "result": {"type": "string", "enum": ["MATCH", "NO_MATCH"]},
                            "status": {"type": "string", "enum": ["PENDING", "PASSED", "FAILED"]}}
    spec = json.loads(json.dumps(SPEC))
    spec["identity"].update({"complete_flag": "status", "complete_value": "passed", "answer_flag": "result"})
    wf = compile_workflow(spec, api, BRIEFS)
    hook = tool(wf, "identify", "verify_identity")["post_process_code"]
    assert "This answer is correct" in run_hook(hook, {"ok": True, "result": "MATCH", "status": "PENDING"})
    assert "NOT correct" in run_hook(hook, {"ok": True, "result": "NO_MATCH", "status": "PENDING"})
    assert "fully verified" in run_hook(hook, {"ok": True, "result": "MATCH", "status": "PASSED"})
    # The gate compares exactly: it takes the API's spelling too.
    gate = [c["operand"] for c in wf["nodes"]["identify"]["transitions"][0]["condition"]["conditions"]]
    assert "PASSED" in gate and "passed" in gate
    # A value the spec names, and a value that is neither right nor wrong, which says nothing.
    spec["identity"].update({"answer_value": "OK_7"})
    hook = tool(compile_workflow(spec, api, BRIEFS), "identify", "verify_identity")["post_process_code"]
    assert "This answer is correct" in run_hook(hook, {"ok": True, "result": "OK_7", "status": "PENDING"})
    assert "did not say" in run_hook(hook, {"ok": True, "result": "SEE_AGENT", "status": "PENDING"})
    # The kit's boolean flags behave as before.
    wf = compile_workflow(SPEC, API, BRIEFS)
    hook = tool(wf, "identify", "verify_identity")["post_process_code"]
    assert "This answer is correct" in run_hook(hook, {"ok": True, "verified": True, "all_verified": False})
    assert "NOT correct" in run_hook(hook, {"ok": True, "verified": False, "all_verified": False, "wrong_answers_left": 1})
    # 1 is a value of its own, not True.
    spec = json.loads(json.dumps(SPEC))
    spec["identity"].update({"complete_flag": "all_verified", "complete_value": 1})
    gate = [c["operand"] for c in compile_workflow(spec, API, BRIEFS)["nodes"]["identify"]["transitions"][0]["condition"]["conditions"]]
    assert "1" in gate


def test_the_call_key_the_clock_and_fixed_api_values_in_tool_bodies():
    api = json.loads(json.dumps(API))
    for path, item in api["paths"].items():
        body = item["post"].get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
        if "customer_id" in body.get("properties", {}):
            body["properties"]["customer_number"] = body["properties"].pop("customer_id")
            body["required"] = ["customer_number" if r == "customer_id" else r for r in body.get("required", [])]
    close = api["paths"]["/close_call"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    close["required"] = close["required"] + ["reason"]
    close["properties"]["channel"] = {"type": "string", "enum": ["voice"]}
    spec = json.loads(json.dumps(SPEC))
    spec["call_variables"] = ["customer_number", "first_name", "last_name", "title", "date"]
    spec["now_variable"] = "date"
    spec["outcomes"]["no_reason"] = ["promise", "paid"]
    wf = compile_workflow(spec, api, BRIEFS)
    verify = tool(wf, "identify", "verify_identity")["function"]["parameters"]["properties"]["body"]
    assert verify["properties"]["customer_number"]["default"] == "{{customer_number}}" and "customer_number" not in verify["required"]
    promise = tool(wf, "negotiate", "create_promise")["function"]["parameters"]["properties"]["body"]
    assert promise["properties"]["date"]["default"] == "{{create_promise_date}}" and "date" in promise["required"]
    closing = tool(wf, "negotiate", "close_call")
    assert closing["function"]["parameters"]["properties"]["body"]["properties"]["channel"]["default"] == "voice"
    assert "[]" in closing["pre_process_code"] and "promise" not in closing["pre_process_code"]
    assert validate_workflow(wf, api) == []
    # A body written as allOf of parts compiles with all their fields.
    api = json.loads(json.dumps(API))
    body = api["paths"]["/create_promise"]["post"]["requestBody"]["content"]["application/json"]
    whole = body["schema"]
    body["schema"] = {"allOf": [{"type": "object", "properties": {"customer_id": whole["properties"]["customer_id"]}, "required": ["customer_id"]},
                                {"type": "object", "properties": {k: v for k, v in whole["properties"].items() if k != "customer_id"},
                                 "required": [r for r in whole.get("required", []) if r != "customer_id"]}]}
    wf = compile_workflow(SPEC, api, BRIEFS)
    promise = tool(wf, "negotiate", "create_promise")["function"]["parameters"]["properties"]["body"]
    assert set(promise["properties"]) == set(whole["properties"])
    assert validate_workflow(wf, api) == []


def test_product_fields_in_a_nested_object_and_amounts_given_as_text():
    api = json.loads(json.dumps(API))
    items = api["paths"]["/get_account"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["properties"]["products"]["items"]
    flat = items["properties"]
    items["properties"] = {"product_id": flat["product_id"], "type": flat["type"], "card": {"type": "object", "properties": {"last4": flat["card_last4"]}},
                           "balance": {"type": "object", "properties": {k: flat[k] for k in ("past_due", "minimum_payment", "instalment_amount")}},
                           "days_late": flat["days_late"]}
    spec = json.loads(json.dumps(SPEC))
    spec["account"].update({"amount_field": "balance.past_due", "floor_field_by_type": {"credit_card": "max(balance.minimum_payment, 5% of balance.past_due)"},
                            "spoken_name_by_type": {"credit_card": "credit card ending <card.last4>"}})
    assert validate_spec(spec, api) == []
    spec["account"]["amount_field"] = "balance.nonsense"
    assert any("amount_field" in i for i in validate_spec(spec, api))
    spec["account"]["amount_field"] = "balance.past_due"
    product = {"product_id": "p1", "type": "credit_card", "card": {"last4": "1234"}, "days_late": 4,
               "balance": {"past_due": "EUR 2,125.10", "minimum_payment": "90.00 €"}}
    out = _facts(spec, [product])
    assert "credit card ending 1234" in out and "2125.1" in out
    assert "floor (max(balance.minimum_payment, 5% of balance.past_due)) 106.26" in out


def test_a_floor_that_is_a_multiple_of_a_field():
    # A held-out brief: the car loan floor is "the lower of twice the instalment and the past-due amount".
    spec = json.loads(json.dumps(SPEC))
    for rule, floor in (("min(2 * instalment_amount, past_due)", "800"), ("instalment_amount x 2", "800"), ("1.5 * instalment_amount", "600")):
        spec["account"]["floor_field_by_type"] = {"credit_card": rule}
        assert validate_spec(spec, API) == [], rule
        out = _facts(spec, [{"product_id": "p1", "type": "credit_card", "card_last4": "1234", "days_late": 4, "past_due": 1250, "instalment_amount": 400}])
        assert "floor (" + rule + ") " + floor in out, (rule, out)
    spec["account"]["floor_field_by_type"] = {"credit_card": "2 * nonsense"}
    assert any("floor 2 * nonsense" in i for i in validate_spec(spec, API))
    snippet = (ROOT/"builder/snippets/facts.py").read_text()
    from builder.generate import TIMES
    assert "TIMES = r\"" + TIMES + "\"" in snippet
