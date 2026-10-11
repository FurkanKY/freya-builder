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


def _facts(spec, products, now="2026-10-21T09:00"):
    wf = compile_workflow(spec, API, BRIEFS)
    code = wf["nodes"]["account_facts"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
    variables = {"now": now, "account_products": json.dumps(products)}
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
    # The brief's fallback for a month's end that is today or earlier: the next month's (Friday 30 October is the last business
    # day of October; Saturday 31st is after it). With no fallback the day stays as computed.
    roll = {"type": "last_business_day_of_month", "roll_forward": "today_or_earlier"}
    assert scope["_deadline"](roll, datetime.date(2026, 10, 30), set(range(5)), {}) == nov30
    assert scope["_deadline"](roll, datetime.date(2026, 10, 31), set(range(5)), {}) == nov30
    assert scope["_deadline"](roll, datetime.date(2026, 10, 29), set(range(5)), {}) == datetime.date(2026, 10, 30)
    assert scope["_deadline"](rule, datetime.date(2026, 10, 30), set(range(5)), {}) == datetime.date(2026, 10, 30)
    first = {"type": "end_of_month", "roll_forward": "before_first_promise_day"}
    assert scope["_deadline"](first, datetime.date(2026, 10, 30), set(range(5)), {}, datetime.date(2026, 11, 2)) == nov30
    assert scope["_deadline"](dict(week, roll_forward="today_or_earlier"), datetime.date(2026, 10, 16), set(range(5)), {}) == datetime.date(2026, 10, 23)
    for raw, want in [("today_or_earlier", "today_or_earlier"), ("if today or earlier", "today_or_earlier"),
                      ("before_first_promise_day", "before_first_promise_day"), ("", ""), (None, "")]:
        spec["account"]["bands"][0]["deadline"] = {"type": "end_of_month", "count": 0, "date": "", "roll_forward": raw}
        assert normalize_spec(spec, API)["account"]["bands"][0]["deadline"]["roll_forward"] == want, raw
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


def test_an_opening_sentence_given_word_for_word_is_kept_unchanged():
    from builder.generate import opening_issues
    # A held-out brief: "The first sentence is, word for word: '... This call is recorded.'" was reworded by the reader.
    briefs = [{"path": "brief.md", "text": "4.1 The first sentence is, word for word: 'Good day, this is the virtual assistant of Freya Bank."
                                           " This call is recorded.' Then ask for the customer by name."}]
    bad = {"opening_line": "Good day, this is the virtual assistant of Freya Bank. We are recording this call. May I speak with {{first_name}}?"}
    assert len(opening_issues(bad, briefs)) == 1 and "This call is recorded." in opening_issues(bad, briefs)[0]
    good = {"opening_line": "Good day, this is the virtual assistant of Freya Bank. This call is recorded. May I speak with {{first_name}}?"}
    assert opening_issues(good, briefs) == []
    # An opening the brief only describes, or a quote with a placeholder, gives no issue.
    for path in ("vendor/kit-v3/briefs/brief-a.md", "vendor/kit-v3/briefs/brief-b.md", "tests/fixtures/geny/brief-y.md"):
        assert opening_issues({"opening_line": "Hello."}, [{"path": path, "text": (ROOT/path).read_text()}]) == [] or "brief-y" in path
    assert opening_issues({"opening_line": "Hi."}, [{"path": "x", "text": 'Open with exactly: "Hello <first name>, this is Acme."'}]) == []


def test_the_wrong_answer_note_states_the_briefs_own_limit():
    # Held-out briefs stop the check after two wrong answers where the service allows three; the note named one API's field.
    for limit, said in ((2, "after 2 wrong answers"), ("two", "after 2 wrong answers"), (None, "count the wrong answers as the policy says")):
        spec = json.loads(json.dumps(SPEC))
        spec["identity"]["max_wrong_answers"] = limit
        wf = compile_workflow(spec, API, [])
        hook = tool(wf, "identify", "verify_identity")["post_process_code"]
        note = run_hook(hook, {"ok": True, "verified": False, "all_verified": False, "wrong_answers_left": 1})
        assert said in note and "wrong_answers_left" not in note, note


def test_a_plan_step_on_the_nth_business_day():
    # A held-out brief: "attempt 1 is the full amount on the 2nd business day after today"; the reader used <next_business_day>.
    spec = json.loads(json.dumps(SPEC))
    band = spec["account"]["bands"][0]
    band["attempt_plan"] = ["attempt 1: <amount> by <next_business_day> computed as the 2nd business day after today"]
    assert any("<business_day_N>" in i and "2nd" in i for i in validate_spec(spec, API))
    band["attempt_plan"][0] = "attempt 1: <amount> by <business_day_2>"
    assert validate_spec(spec, API) == []
    band["attempt_plan"][0] = "attempt 1: <amount> by <next_business_day>, or within 5 business days"
    assert validate_spec(spec, API) == []
    band["attempt_plan"][0] = "attempt 1: <amount> by <business_day_2>"
    # Friday 16 October 2026: the 1st business day after today is Monday 19, the 2nd is Tuesday 20.
    out = _facts(spec, [{"product_id": "p1", "type": "credit_card", "card_last4": "1234", "days_late": band["min"], "past_due": 365}],
                 now="2026-10-16T10:00:00")
    assert "attempt 1: 365 by 2026-10-20 (Tuesday, 20 October 2026)" in out, out


def test_on_the_last_business_day_of_the_week_the_step_names_next_weeks():
    # Brief A: "Attempt 1: propose the last business day of this week. If today is that day, propose the last business day of
    # next week." On a Friday the step names next week's day only; the condition was left to the phone model before.
    spec = json.loads(json.dumps(SPEC))
    band = spec["account"]["bands"][0]
    product = [{"product_id": "p1", "type": "credit_card", "card_last4": "1234", "days_late": band["min"], "past_due": 365}]
    for step in ["attempt 1: propose <amount> by <last_business_day_this_week>; if today is that day, propose <last_business_day_next_week> instead",
                 "attempt 1: propose <last_business_day_this_week> (or <last_business_day_next_week> if today is that day) for <amount>",
                 "attempt 1: propose <amount> by <last_business_day_this_week>, or next week's last business day if today is that day"]:
        band["attempt_plan"] = [step]
        friday = _facts(spec, product, now="2026-10-16T10:00:00")
        assert "2026-10-23 (Friday, 23 October 2026)" in friday and "2026-10-16 (Friday" not in friday.split("PERSUASION PLAN")[1], step
        wednesday = _facts(spec, product, now="2026-10-14T10:00:00")
        assert "2026-10-16 (Friday, 16 October 2026)" in wednesday.split("PERSUASION PLAN")[1], step
        # On another day the alternative names this week's day as well: no second day to take for another proposal.
        if "<last_business_day_next_week>" in step:
            assert "2026-10-23" not in wednesday.split("PERSUASION PLAN")[1], step
    # Without the condition the token keeps its own day, also on a Friday.
    band["attempt_plan"] = ["attempt 1: propose <amount> by <last_business_day_this_week>"]
    assert "365 by 2026-10-16 (Friday, 16 October 2026)" in _facts(spec, product, now="2026-10-16T10:00:00")


def test_the_calendar_stops_after_six_weeks_and_a_later_day_is_still_checked():
    # The code node gets at most 128 KB of code and call data together; a fixed deadline at the year's end would give a
    # calendar line for each of 70 days.
    spec = json.loads(json.dumps(SPEC))
    band = spec["account"]["bands"][0]
    band["deadline"] = {"type": "fixed_date", "count": 0, "date": "2026-12-31"}
    wf = compile_workflow(spec, API, BRIEFS)
    code = wf["nodes"]["check_date"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
    variables = {"now": "2026-10-21T09:00", "named_day_words": "15 December", "account_products": json.dumps(
        [{"product_id": "p1", "type": "credit_card", "card_last4": "1234", "days_late": band["min"], "past_due": 365}])}
    exec(compile(code, "facts", "exec"), {"vars": variables})
    calendar = variables["date_facts"].split("Calendar, one line per day from today.")[1]
    assert "\n2026-12-05 " in calendar and "\n2026-12-06 " not in calendar
    assert "2026-12-15" in variables["named_day_facts"] and "business day" in variables["named_day_facts"], variables["named_day_facts"]


def test_a_failed_service_call_is_no_wrong_answer_and_a_failed_account_load_is_said():
    wf = compile_workflow(json.loads(json.dumps(SPEC)), API, BRIEFS)
    hook = tool(wf, "identify", "verify_identity")["post_process_code"]
    result = {"status": "error", "status_code": 500, "message": "Request failed with status 500", "data": None}
    exec(hook, {"result": result})
    note = result["data"]["what_to_do_next"]
    assert "FAILED" in note and "not counted as a wrong answer" in note and "same field and answer" in note, note
    # A refused answer (ok false, HTTP 200) is still the service's own judgement.
    assert "Ask the customer again" in run_hook(hook, {"ok": False, "error": "unknown field"})
    assert wf["nodes"]["load_account"]["pre_actions"][0]["config"]["maxRetries"] == 1
    code = wf["nodes"]["account_facts"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
    variables = {"now": "2026-10-21T09:00", "load_account_response.status_code": 500, "load_account_response.status": "error"}
    exec(compile(code, "facts", "exec"), {"vars": variables})
    assert variables["account_facts"].startswith("get_account FAILED (500") and variables["facts_state"] == "load_failed"
    variables = {"now": "2026-10-21T09:00"}
    exec(compile(code, "facts", "exec"), {"vars": variables})
    assert variables["facts_state"] == "no_products"


def _without(api, *tools):
    api = json.loads(json.dumps(API))
    api["paths"] = {p: v for p, v in api["paths"].items() if p.strip("/") not in tools}
    return api


def test_each_operation_is_checked_on_its_own_and_optional_product_fields_may_be_empty():
    # A contract without close_call or add_note: the account is still checked, and nothing is said about the missing ones.
    spec = json.loads(json.dumps(SPEC))
    spec["account"]["list_field"] = "nonsense"
    issues = validate_spec(spec, _without(API, "close_call", "add_note"))
    assert issues == ["account.list_field nonsense is not in get_account response"]
    assert validate_spec(SPEC, _without(API, "close_call", "verify_identity", "get_account")) == []
    # A bad verify_identity schema costs only its own checks.
    api = json.loads(json.dumps(API))
    api["paths"]["/verify_identity"]["post"]["requestBody"] = "see the contract"
    issues = validate_spec(spec, api)
    assert any(i.startswith("spec could not be checked against verify_identity") for i in issues) and any("list_field" in i for i in issues)
    # One product type and no bands: no type or segment field to name.
    spec = json.loads(json.dumps(SPEC))
    spec["account"].update(type_field="", segment_field="", bands=[], floor_field_by_type={"card": "minimum_payment"},
                           spoken_name_by_type={"card": "your card"})
    assert validate_spec(spec, API) == []
    spec["account"]["segment_field"] = "invented_field"
    assert validate_spec(spec, API) == []
    # Several bands need the field that selects one.
    spec["account"].update(segment_field="", bands=[dict(SPEC["account"]["bands"][0]), dict(SPEC["account"]["bands"][0], min=11, max=90)])
    assert any("segment_field is empty" in i for i in validate_spec(spec, API))
    # A success response written as 201 is still the account's schema.
    api = json.loads(json.dumps(API))
    responses = api["paths"]["/get_account"]["post"]["responses"]
    responses["201"] = responses.pop("200")
    assert validate_spec(SPEC, api) == []


def test_identity_answers_in_one_call_are_checked_against_the_request_fields():
    api = json.loads(json.dumps(API))
    body = api["paths"]["/verify_identity"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    body["properties"] = {"customer_id": {"type": "string"}, "date_of_birth": {"type": "string"}, "phone_last4": {"type": "string"}}
    assert not [i for i in validate_spec(SPEC, api) if "identity field" in i]
    # The only enum property is the field list, whatever its name.
    body["properties"] = {"customer_id": {"type": "string"}, "soru": {"type": "string", "enum": ["dogum_tarihi"]}, "cevap": {"type": "string"}}
    assert any("identity field date_of_birth" in i for i in validate_spec(SPEC, api))
    # One call for all answers, with an unrelated enum property: the fields are the request's.
    body["properties"] = {"kanal": {"type": "string", "enum": ["ivr"]}, "dogumTarihi": {"type": "string"}, "PHONE_LAST4": {"type": "string"}}
    spec = json.loads(json.dumps(SPEC))
    spec["identity"]["questions"] = [dict(spec["identity"]["questions"][0], field="dogum_tarihi"), dict(spec["identity"]["questions"][1], field="phone_last4")]
    assert not [i for i in validate_spec(spec, api) if "identity field" in i]
    # A field that is neither the enum's nor the request's is checked in the mode the other fields point to.
    spec["identity"]["questions"][1]["field"] = "tc_son4"
    for _ in range(2):
        assert [i.split(" request")[0] for i in validate_spec(spec, api) if "identity field" in i] == ["identity field tc_son4 is not a verify_identity"]
        body["properties"].pop("kanal", None)
    body["properties"] = {"customer_id": {"type": "string"}, "field": {"type": "string", "enum": ["date_of_birth", "phone_last4"]}, "value": {"type": "string"}}
    spec["identity"]["questions"][0]["field"], spec["identity"]["questions"][1]["field"] = "date_of_birth", "value"
    assert any("identity field value is not in verify_identity enum" in i for i in validate_spec(spec, api))


def test_the_language_is_named_once_and_a_missing_one_is_reported():
    from builder.spec import language_name
    for raw in ("Türkçe", "TÜRKÇE", "turkish", "tr", "tr-TR", "TR_tr", "Türk dili"):
        assert normalize_spec(dict(SPEC, language=raw), API)["language"] == "Turkish", raw
    for raw in ("English", "en", "en-GB", "İngilizce"):
        assert normalize_spec(dict(SPEC, language=raw), API)["language"] == "English", raw
    assert language_name("Spanish") == "Spanish" and language_name("Spanish (formal)") == "Spanish (formal)"
    for raw in ("Turkish (formal)", "Türkçe (resmi dil)", "Turkish, English on request", "tr-TR / en", "Türkçe - siz hitabıyla"):
        assert language_name(raw) == "Turkish", raw
    assert validate_spec(dict(SPEC, language="Türkçe"), API) == [] and validate_spec(dict(SPEC, language="Spanish"), API) == []
    for raw in (None, "", "<language the agent speaks>", "the customer's language", "same as the customer"):
        assert [i for i in validate_spec(dict(SPEC, language=raw), API) if i.startswith("spec.language")], raw


def test_turkish_call_variables_show_only_who_the_call_is_for():
    from builder.spec import who_variables
    who = ["musteri_adi", "müşteriSoyadı", "ad_soyad", "AD_SOYAD", "kart_sahibi", "unvan", "hitap", "cinsiyet", "ISIM", "musteri"]
    data = ["dogum_tarihi", "DOĞUM_TARİHİ", "kart_son4", "son_dort_hane", "borc_tutari", "asgari_odeme", "tc_kimlik_no", "tckn",
            "telefon", "cep_tel", "adres", "musteri_no", "hesap_numarasi", "ekstre_borcu", "son_odeme_tarihi", "gecikme_gunu", "bakiye"]
    others = ["temsilci_adi", "banka_adi", "urun_adi", "asistan_adi"]
    spec = {"call_variables": who + data + others + ["simdi"], "now_variable": "simdi"}
    assert who_variables(spec) == who
    # The English names keep their side.
    english = {"call_variables": ["customer_id", "first_name", "last_name", "title", "now", "client_ref", "given_name", "card_holder",
                                  "address", "amount_due", "agent_name", "customer"], "now_variable": "now"}
    assert who_variables(english) == ["first_name", "last_name", "title", "given_name", "card_holder", "customer"]
    # A holder's own data is no name: it stays out of reach until the identity is verified.
    held = {"call_variables": ["kart_sahibi_adi", "cardHolderName", "kart_sahibi_dogum_tarihi", "hesap_sahibi_tckn", "account_holder_dob"],
            "now_variable": "now"}
    assert who_variables(held) == ["kart_sahibi_adi", "cardHolderName"]


def test_turkish_calendar_and_limit_words_are_normalised():
    assert weekdays("Pazartesi-Cuma") == WEEKDAYS_5
    assert weekdays("Pazartesi'den Cuma'ya kadar") == WEEKDAYS_5 == weekdays("pazartesiden cumaya")
    assert weekdays("Pazartesi ile Cuma arası") == WEEKDAYS_5
    assert weekdays("Pazartesi ve Cuma") == ["Monday", "Friday"]
    assert weekdays(["Salı", "ÇARŞAMBA", "Perşembe"]) == ["Tuesday", "Wednesday", "Thursday"]
    assert weekdays("hafta içi ve cumartesi") == WEEKDAYS_5 + ["Saturday"]
    assert weekdays("Cumartesi, Pazar") == ["Saturday", "Sunday"] and weekdays("pazarlama") == []
    assert weekdays("Pzt-Cum") == WEEKDAYS_5 and weekdays(["Pzt", "Sal"]) == ["Monday", "Tuesday"]
    # An English text with no day name keeps the default: 'per' is no Thursday here.
    assert weekdays("five days per week") == [] and weekdays("weekdays") == []
    cases = [("closed_day_rule", "bir sonraki iş günü", "next_business_day"), ("closed_day_rule", "Bir önceki iş gününe çek", "previous_business_day"),
             ("closed_day_rule", "müşteriden başka bir gün iste", "ask_again"), ("earliest_promise_day", "yarın", "tomorrow"),
             ("earliest_promise_day", "Bugün olamaz", "tomorrow"), ("earliest_promise_day", "bugün", "today"),
             ("next_weekday", "haftaya", "following_week"), ("next_weekday", "en yakın gelen gün", "coming")]
    for key, raw, want in cases:
        spec = json.loads(json.dumps(SPEC))
        spec["calendar"][key] = raw
        assert normalize_spec(spec, API)["calendar"][key] == want, raw
    for raw, want in (("iki yanlış cevap", 2), ("en fazla üç", 3), ("3", 3), ("three wrong answers", 3), ("Üç", 3), ("hiç", None)):
        spec = json.loads(json.dumps(SPEC))
        spec["identity"]["max_wrong_answers"] = raw
        assert normalize_spec(spec, API)["identity"]["max_wrong_answers"] == want, raw


WEEKDAYS_5 = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


def test_a_turkish_opening_given_word_for_word_is_kept_unchanged():
    from builder.generate import opening_issues
    quote = "İyi günler, Freya Bank'tan arıyorum. Bu görüşme kaydediliyor."
    for text in (f"Açılış cümlesi aynen şöyledir: '{quote}'", f"AÇILIŞ: asistan kelimesi kelimesine şunu söyler:\n“{quote}”",
                 f"Aramayı şu cümleyle açın: «{quote}»"):
        briefs = [{"path": "analiz.docx", "text": text}]
        assert len(opening_issues({"opening_line": "Merhaba, Freya Bank'tan arıyorum."}, briefs)) == 1, text
        assert opening_issues({"opening_line": quote + " {{ad}} Bey ile mi görüşüyorum?"}, briefs) == [], text


def test_tool_descriptions_keyed_by_path_take_the_tool_name():
    api = json.loads(json.dumps(API))
    api["paths"]["/v1/sms/{customer_id}"] = {"post": {"operationId": "send_sms", "responses": {}}}
    api["paths"]["/v1/odeme-linki"] = {"post": {"responses": {}}}
    spec = dict(SPEC, tool_descriptions={"POST /close_call": "close", "/v1/sms/{customer_id}": "sms", "POST /v1/odeme-linki": "link",
                                         "add_note": "note"},
                tool_field_hints={"post /v1/sms/{customer_id}": {"text": "short"}})
    out = normalize_spec(spec, api)
    assert out["tool_descriptions"] == {"close_call": "close", "send_sms": "sms", "odeme_linki": "link", "add_note": "note"}
    assert out["tool_field_hints"] == {"send_sms": {"text": "short"}}
    # The contract's own operation name (kept by case.apply_roles) and a tool name written in camelCase.
    api["paths"]["/close_call"]["post"]["x-contract-operation-id"] = "gorusmeyiKapat"
    spec = dict(SPEC, tool_descriptions={"gorusmeyiKapat": "close", "sendSms": "sms", "odemeLinki": "link", "unknownTool": "x"})
    assert normalize_spec(spec, api)["tool_descriptions"] == {"close_call": "close", "send_sms": "sms", "odeme_linki": "link", "unknownTool": "x"}


def test_turkish_placeholders_become_call_variables_or_are_reported():
    spec = dict(SPEC, call_variables=["musteri_no", "müşteri_adı", "simdi"], now_variable="simdi",
                opening_line="İyi günler {Müşteri Adı}, ben Freya Bank'ın dijital asistanıyım. {MUSTERI_ADI} ile mi görüşüyorum?")
    out = normalize_spec(spec, API)
    assert out["opening_line"] == "İyi günler {{müşteri_adı}}, ben Freya Bank'ın dijital asistanıyım. {{müşteri_adı}} ile mi görüşüyorum?"
    spec["opening_line"] = "İyi günler [İsim Soyisim], ben Freya Bank'ın dijital asistanıyım."
    assert any("[İsim Soyisim]" in i for i in validate_spec(spec, API))
    # A quote with a filled-in part is not compared word for word.
    from builder.generate import opening_issues
    briefs = [{"path": "analiz.docx", "text": "Açılış cümlesi aynen şöyledir: 'İyi günler, (ad soyad) ile mi görüşüyorum?'"}]
    assert opening_issues({"opening_line": "İyi günler, {{müşteri_adı}} ile mi görüşüyorum?"}, briefs) == []


def _account_response(schema):
    api = json.loads(json.dumps(API))
    api["paths"]["/get_account"]["post"]["responses"]["200"]["content"]["application/json"]["schema"] = schema
    return api


def test_the_account_may_come_back_as_one_object_or_a_top_level_array():
    array = API["paths"]["/get_account"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["properties"]["products"]
    flat, nested = array["items"], {"type": "object", "properties": {"ok": {"type": "boolean"}, "statement": array["items"]}}
    for schema, field in ((flat, ""), (flat, None), (array, ""), (nested, "statement")):
        api, spec = _account_response(schema), json.loads(json.dumps(SPEC))
        spec["account"]["list_field"] = field
        assert validate_spec(spec, api) == [], (schema, field)
        assert normalize_spec(spec, api)["account"]["product_types"] == ["credit_card", "personal_loan", "car_loan"]
        assert validate_workflow(compile_workflow(spec, api, BRIEFS), api) == []
    # The one product's fields are still checked, and a wrapped response still needs its list_field.
    spec = json.loads(json.dumps(SPEC))
    spec["account"].update(list_field="", id_field="statement_no")
    assert validate_spec(spec, _account_response(flat)) == ["account.id_field statement_no is not a product field"]
    spec["account"]["id_field"] = "product_id"
    assert "account.id_field product_id is not a product field" in validate_spec(spec, _account_response(nested))
    spec["account"]["list_field"] = "missing"
    assert validate_spec(spec, _account_response(nested))[0] == "account.list_field missing is not in get_account response"


def test_text_that_names_a_tool_the_bank_lacks_is_reported():
    api, spec = _without(API, "close_call", "add_note"), json.loads(json.dumps(SPEC))
    spec["policy"]["after_verification"] = "1. Gerekirse add_note ile not düş.\n2. Sonra close_call'u çağır."
    assert [i.split(",")[0] for i in validate_spec(spec, api)] == ["the spec names add_note", "the spec names close_call"]
    # A description keyed by a missing tool never reaches the agent; a contract with every tool may name them all.
    spec["policy"]["after_verification"] = "1. Ask for payment."
    spec["tool_descriptions"] = {"close_call": "CALL it last.", "create_promise": "CALL it after a yes, then add_notes."}
    assert validate_spec(spec, api) == []
    spec["policy"]["closing"] = "close_call with outcome promise; add_note first"
    assert validate_spec(spec, API) == []
