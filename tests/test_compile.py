import datetime
import json
import time
from pathlib import Path
from builder.compile import compile_workflow
from builder.generate import validate_spec
from builder.runtime import validate_workflow, walk

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
        start = time.monotonic()
        exec(tool["pre_process_code"], {"config": config})
        assert ("reason" in config["body"]) == kept
        # close_call waits so that tool calls sent in the same turn reach the bank first.
        assert time.monotonic() - start >= 1.4


def test_facts_compute_deadline_from_spec_and_skip_holiday():
    wf = compile_workflow(SPEC, API, BRIEFS)
    products = [{"product_id": "p1", "type": "credit_card", "card_last4": "1234", "past_due": 300.0, "days_late": 4, "minimum_payment": 90.0}]
    out = run_facts(wf, {"now": "2026-10-21T09:00", "account_products": json.dumps(products)})
    # 5 business days after Wed 21 Oct, skipping the weekend and the 26 Oct holiday: 22, 23, 27, 28, 29.
    assert "deadline 2026-10-29" in out["account_facts"]
    assert "credit card ending 1234" in out["account_facts"]
    assert "2026-10-26 Monday: HOLIDAY (bank holiday), NOT a business day; previous business day 2026-10-23 Friday; next business day 2026-10-27 Tuesday; on or before the deadline of p1" in out["date_facts"]
    assert "Tomorrow: 2026-10-22 (Thursday, 22 October 2026), a business day." in out["date_facts"]
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


def test_spec_accepts_a_nested_product_list():
    api = json.loads(json.dumps(API))
    _, op = next((path, item.get("post")) for path, item in api["paths"].items() if path.endswith("get_account"))
    schema = op["responses"]["200"]["content"]["application/json"]["schema"]
    schema["properties"] = {"ok": schema["properties"].get("ok", {"type": "boolean"}),
                            "customer": {"type": "object", "properties": {"products": schema["properties"]["products"]}}}
    spec = json.loads(json.dumps(SPEC))
    spec["account"]["list_field"] = "customer.products"
    assert not [i for i in validate_spec(spec, api) if "list_field" in i or "product field" in i]
    wf = compile_workflow(spec, api, BRIEFS)
    assert wf["nodes"]["load_account"]["response_mapping"][0]["path"] == "data.customer.products"


def test_facts_name_the_earliest_of_differing_deadlines():
    spec = json.loads(json.dumps(SPEC))
    spec["account"]["bands"].append({"name": "late", "min": 11, "max": 90, "deadline": {"type": "business_days_after_today", "count": 2, "date": ""}, "persuasion_attempts": 2})
    wf = compile_workflow(spec, API, BRIEFS)
    products = [{"product_id": "p1", "type": "credit_card", "card_last4": "1234", "past_due": 300.0, "days_late": 4, "minimum_payment": 90.0},
                {"product_id": "p2", "type": "credit_card", "card_last4": "5678", "past_due": 200.0, "days_late": 30, "minimum_payment": 60.0}]
    out = run_facts(wf, {"now": "2026-10-21T09:00", "account_products": json.dumps(products)})
    assert "Deadlines differ: the earliest is 2026-10-23 (Friday, 23 October 2026) (p2)." in out["account_facts"]
    assert "p1 deadline 2026-10-29; p2 deadline 2026-10-23." in out["account_facts"]
    assert out["product_count"] == "2"
    same = run_facts(wf, {"now": "2026-10-21T09:00", "account_products": json.dumps(products[:1] + [dict(products[1], days_late=5)])})
    assert "Deadlines differ" not in same["account_facts"]


def test_named_day_is_checked_in_code_and_cleared():
    wf = compile_workflow(SPEC, API, BRIEFS)
    assert validate_workflow(wf, API) == []
    negotiate = wf["nodes"]["negotiate"]
    assert negotiate["extraction_schema"][0]["name"] == "named_day_words"
    assert negotiate["extraction_schema"][0]["type"] == "string"
    assert [t["target_node"] for t in negotiate["transitions"]] == ["hang_up", "check_date"]
    assert wf["nodes"]["check_date"]["passthrough_default_transition"] == "negotiate"
    assert "{{named_day_facts}}" in negotiate["task_message"]
    products = [{"product_id": "p1", "type": "credit_card", "card_last4": "1234", "past_due": 300.0, "days_late": 4, "minimum_payment": 90.0}]
    out = run_facts(wf, {"now": "2026-10-21T09:00", "account_products": json.dumps(products)})
    assert out["named_day_facts"] == "No exact day named yet."
    out = run_facts(wf, dict(out, named_day_words="Monday the 26th"))
    assert out["named_day_words"] == "none"
    assert "2026-10-26 Monday: HOLIDAY (bank holiday), NOT a business day; previous business day 2026-10-23 Friday; next business day 2026-10-27 Tuesday; on or before the deadline of p1" in out["named_day_facts"]
    out = run_facts(wf, dict(out, named_day_words="the seventh of November"))
    assert "2026-11-07 Saturday: weekend, NOT a business day" in out["named_day_facts"]
    assert "AFTER the deadline of p1 (p1 deadline 2026-10-29 Thursday)" in out["named_day_facts"]
    # Unreadable words leave the last check in place and never raise.
    out = run_facts(wf, dict(out, named_day_words="when my salary comes"))
    assert out["named_day_words"] == "none" and "2026-11-07" in out["named_day_facts"]
    out = run_facts(wf, dict(out))
    assert "2026-11-07" in out["named_day_facts"]
    out = run_facts(wf, dict(out, named_day_words="Tuesday the 26th"))
    assert "The customer said Tuesday, but that date is a Monday" in out["named_day_facts"]


def test_day_words_resolve_from_the_call_date_not_the_server_clock():
    wf = compile_workflow(SPEC, API, BRIEFS)
    code = wf["nodes"]["check_date"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
    scope = {"vars": {"now": "2026-10-14T11:00"}}
    exec(compile(code, "facts", "exec"), scope)
    resolve, today = scope["_resolve_day"], datetime.date(2026, 10, 14)  # a Wednesday
    iso = lambda words: [d.isoformat() for d in resolve(words, today)]
    assert iso("tomorrow") == ["2026-10-15"]
    assert iso("the day after tomorrow") == ["2026-10-16"]
    assert iso("Friday") == ["2026-10-16"]
    assert iso("next Friday") == ["2026-10-16", "2026-10-23"]
    assert iso("Friday next week") == ["2026-10-23"]
    assert iso("Wednesday") == ["2026-10-14", "2026-10-21"]
    assert iso("the twenty-sixth") == ["2026-10-26"]
    assert iso("twenty six October") == ["2026-10-26"]
    assert iso("October 30") == ["2026-10-30"]
    assert iso("the 5th") == ["2026-11-05"]
    assert iso("the thirty first") == ["2026-10-31"]
    assert iso("the first of January") == ["2027-01-01"]
    assert iso("I can pay 200 then") == []
    assert iso("I may pay later") == []
    assert iso("the week after next") == []


def test_persuasion_plan_is_an_explicit_chain_with_a_stop():
    spec = json.loads(json.dumps(SPEC))
    spec["account"]["bands"][0]["attempt_plan"] = ["attempt 1: propose <amount> by <last_business_day_this_week>", "Attempt 2 - propose <floor> by <deadline>"]
    wf = compile_workflow(spec, API, BRIEFS)
    products = [{"product_id": "p1", "type": "credit_card", "card_last4": "1234", "past_due": 300.0, "days_late": 4, "minimum_payment": 90.0}]
    out = run_facts(wf, {"now": "2026-10-23T09:00", "account_products": json.dumps(products)})
    facts = out["account_facts"]
    assert "after the first ask is refused: attempt 1: propose 300 by 2026-10-23 (Friday, 23 October 2026)" in facts
    assert "after attempt 1 is refused: attempt 2: propose 90 by" in facts
    assert "after attempt 2 is refused: STOP, no more payment proposals for p1 (it gets 2 proposals after the first ask" in facts
    assert "attempt 1: attempt 1" not in facts
    assert "Today IS that day." in out["date_facts"]


def test_refusals_are_counted_per_product_in_code():
    spec = json.loads(json.dumps(SPEC))
    step1 = "attempt 1: propose <last_business_day_this_week> for <amount>"
    spec["account"]["bands"] = [
        {"name": "early", "min": 1, "max": 10, "deadline": {"type": "business_days_after_today", "count": 5, "date": ""},
         "persuasion_attempts": 1, "attempt_plan": [step1]},
        {"name": "late", "min": 11, "max": 45, "deadline": {"type": "business_days_after_today", "count": 7, "date": ""},
         "persuasion_attempts": 2, "attempt_plan": [step1, "attempt 2: propose <floor> on <deadline>"]}]
    wf = compile_workflow(spec, API, BRIEFS)
    assert validate_workflow(wf, API) == []
    negotiate = wf["nodes"]["negotiate"]
    assert [f["name"] for f in negotiate["extraction_schema"]] == ["named_day_words", "refused_products", "proposed_products", "dated_products"]
    assert [c["conditions"][0]["variable"] for c in negotiate["transitions"][1]["condition"]["conditions"]] == ["named_day_words", "refused_products"]
    assert "{{plan_state}}" in negotiate["task_message"]
    products = [{"product_id": "p1", "type": "credit_card", "card_last4": "9015", "past_due": 510.0, "days_late": 16, "minimum_payment": 153.0},
                {"product_id": "p2", "type": "personal_loan", "past_due": 1320.0, "days_late": 16, "instalment_amount": 440.0},
                {"product_id": "p3", "type": "car_loan", "past_due": 140.0, "days_late": 7, "instalment_amount": 46.0}]
    out = run_facts(wf, {"now": "2026-10-14T11:00", "account_products": json.dumps(products)})
    assert "p2 personal loan: refused 0 times; nothing refused yet." in out["plan_state"]
    # "I'll pay the card tomorrow, not the personal loan or the car loan": the first ask is refused for the two loans.
    out = run_facts(wf, dict(out, refused_products="the personal loan or the car loan"))
    assert out["refused_products"] == "none"
    assert "p1 credit card ending 9015: refused 0 times" in out["plan_state"]
    assert "p2 personal loan: refused 1 time -> next proposal for p2: attempt 1: propose 2026-10-16 (Friday, 16 October 2026) for 1320." in out["plan_state"]
    assert "p3 car loan: refused 1 time -> next proposal for p3: attempt 1: propose 2026-10-16 (Friday, 16 October 2026) for 140." in out["plan_state"]
    # The same words are not counted twice when the next message refuses nothing.
    out = run_facts(wf, dict(out))
    assert '"p2": 1' in out["refusal_counts"]
    out = run_facts(wf, dict(out, refused_products="personal loan"))
    assert "p2 personal loan: refused 2 times -> next proposal for p2: attempt 2: propose 440 on 2026-10-23" in out["plan_state"]
    out = run_facts(wf, dict(out, refused_products="Personal Loan"))
    assert "p2 personal loan: refused 3 times -> STOP: its 2 proposals after the first ask are used; make no more payment proposals for p2" in out["plan_state"]
    out = run_facts(wf, dict(out, refused_products="car loan"))
    assert "p3 car loan: refused 2 times -> STOP: its 1 proposal after the first ask is used" in out["plan_state"]
    assert "p1 credit card ending 9015: refused 0 times" in out["plan_state"]
    # Group words: a shared word picks every product that has it, 'all' picks every product, 'the others' nothing.
    out = run_facts(wf, {"now": "2026-10-14T11:00", "account_products": json.dumps(products), "refused_products": "the loans"})
    assert json.loads(out["refusal_counts"]) == {"p2": 1, "p3": 1}
    # With no known proposal, a group refusal counts only for the product being worked on, in bank order.
    out = run_facts(wf, dict(out, refused_products="all of them"))
    assert json.loads(out["refusal_counts"]) == {"p2": 2, "p3": 1}
    out = run_facts(wf, dict(out, refused_products="the others"))
    assert json.loads(out["refusal_counts"]) == {"p2": 2, "p3": 1} and out["refused_products"] == "none"
    # A product first refused after the first ask was on its attempt 1.
    out = run_facts(wf, dict(out, refused_products="the card ending 9015"))
    assert json.loads(out["refusal_counts"])["p1"] == 2
    out = run_facts(wf, {"now": "2026-10-14T11:00", "account_products": json.dumps(products), "refused_products": "all except the credit card"})
    assert json.loads(out["refusal_counts"]) == {"p2": 1, "p3": 1}
    # A bare "no" goes to the one product still in its plan, and to none when several are.
    out = run_facts(wf, {"now": "2026-10-14T11:00", "account_products": json.dumps(products), "refusal_counts": json.dumps({"p2": 1, "p3": 2}), "refused_products": "no"})
    assert json.loads(out["refusal_counts"]) == {"p2": 2, "p3": 2}
    out = run_facts(wf, dict(out, refusal_counts=json.dumps({"p2": 1, "p3": 1}), refused_products="no"))
    assert json.loads(out["refusal_counts"]) == {"p2": 1, "p3": 1}
    # One product keeps the model's own counting and the counter stays out of its routing.
    out = run_facts(wf, {"now": "2026-10-14T11:00", "account_products": json.dumps(products[:1]), "refused_products": "credit card"})
    assert out["plan_state"].startswith("One product:")
    assert {"variable": "product_count", "operator": "not_equals", "operand": "1"} in negotiate["transitions"][1]["condition"]["conditions"][1]["conditions"]


def test_only_proposals_the_assistant_made_are_counted():
    spec = json.loads(json.dumps(SPEC))
    step1 = "attempt 1: propose <last_business_day_this_week> for <amount>"
    spec["account"]["bands"] = [
        {"name": "early", "min": 1, "max": 10, "deadline": {"type": "business_days_after_today", "count": 5, "date": ""},
         "persuasion_attempts": 1, "attempt_plan": [step1]},
        {"name": "late", "min": 11, "max": 45, "deadline": {"type": "business_days_after_today", "count": 7, "date": ""},
         "persuasion_attempts": 2, "attempt_plan": [step1, "attempt 2: propose <floor> on <deadline>"]}]
    wf = compile_workflow(spec, API, BRIEFS)
    products = [{"product_id": "p1", "type": "credit_card", "card_last4": "9015", "past_due": 510.0, "days_late": 16, "minimum_payment": 153.0},
                {"product_id": "p2", "type": "personal_loan", "past_due": 1320.0, "days_late": 16, "instalment_amount": 440.0},
                {"product_id": "p3", "type": "car_loan", "past_due": 140.0, "days_late": 7, "instalment_amount": 46.0}]
    base = {"now": "2026-10-14T11:00", "account_products": json.dumps(products)}
    # The extraction's 'nothing refused' value in other spellings counts nothing; 'none of them' refuses every product.
    for word in ["None.", "nothing", "'none'", "none (accepted)", "Nothing refused", "N/A"]:
        out = run_facts(wf, dict(base, refusal_counts=json.dumps({"p2": 1}), refused_products=word))
        assert json.loads(out["refusal_counts"]) == {"p2": 1}, word
        assert out["refused_products"] == "none"
    out = run_facts(wf, dict(base, refused_products="none of them", proposed_products="all"))
    assert json.loads(out["refusal_counts"]) == {"p1": 1, "p2": 1, "p3": 1}
    # A group refusal during the card's proposal uses only the card's step.
    out = run_facts(wf, dict(out, refused_products="all", proposed_products="credit card"))
    assert json.loads(out["refusal_counts"]) == {"p1": 2, "p2": 1, "p3": 1}
    assert out["proposed_products"] == "none"
    # A bare "no" answers what was just proposed.
    out = run_facts(wf, dict(out, refused_products="no", proposed_products="the car loan"))
    assert json.loads(out["refusal_counts"]) == {"p1": 2, "p2": 1, "p3": 2}
    assert out["plan_state"].startswith("The customer has just refused the last proposal allowed for p3 car loan. It is done: propose no"
                                        " amount and no date for it any more.")
    # No figure of a finished product is left to repeat: its fact line drops the floor, the plan and the raw record.
    p3_line = next(l for l in out["account_facts"].splitlines() if "p3" in l)
    assert "DONE" in p3_line and "46" not in p3_line and "140" not in p3_line and "46" not in out["plan_state"].split("\n")[0]
    # The STOP line for a product is said once, on the turn its last proposal is refused.
    out = run_facts(wf, dict(out, refused_products="personal loan", proposed_products="personal loan"))
    assert json.loads(out["refusal_counts"]) == {"p1": 2, "p2": 2, "p3": 2}
    assert out["plan_state"].startswith("Refusals counted by code")
    # A first ask that was answered without a counted refusal: the first proposal of a product is still its attempt 1.
    out = run_facts(wf, dict(base, refused_products="I am not paying the personal loan", proposed_products="personal loan"))
    assert json.loads(out["refusal_counts"]) == {"p2": 2}
    # The first ask answered for some products counts once for those only, whatever was proposed.
    out = run_facts(wf, dict(base, refused_products="personal loan, car loan", proposed_products="all of them"))
    assert json.loads(out["refusal_counts"]) == {"p2": 1, "p3": 1}
    out = run_facts(wf, dict(out, refused_products="personal loan, car loan", proposed_products="personal loan"))
    assert json.loads(out["refusal_counts"]) == {"p2": 2, "p3": 1}
    # A group refusal after a message that proposed nothing ("Go on.", a reason) counts only for the product being worked on.
    start = dict(base, refusal_counts=json.dumps({"p1": 1, "p2": 1, "p3": 1}))
    out = run_facts(wf, dict(start, refused_products="none of them", proposed_products="none"))
    assert json.loads(out["refusal_counts"]) == {"p1": 2, "p2": 1, "p3": 1}
    assert out["plan_state"].startswith("Refusals counted by code")
    # Wordy 'nothing refused' values count nothing, also for the product just proposed.
    for word in ["No refusals", "N/A (accepted)", "not refused", "no refusal - accepted Friday", "Customer accepted", "No products refused"]:
        out = run_facts(wf, dict(base, refusal_counts=json.dumps({"p1": 3, "p2": 2, "p3": 1}), refused_products=word, proposed_products="personal loan"))
        assert json.loads(out["refusal_counts"]) == {"p1": 3, "p2": 2, "p3": 1}, word
    for word in ["No.", "nope", "I won't pay that", "refused", "not paying it"]:
        out = run_facts(wf, dict(base, refusal_counts=json.dumps({"p1": 3, "p2": 2, "p3": 1}), refused_products=word, proposed_products="personal loan"))
        assert json.loads(out["refusal_counts"]) == {"p1": 3, "p2": 3, "p3": 1}, word
    # "I can pay both on the 30th": refusing the agent's answer to the customer's own day is that product's answer to the
    # first ask, so attempt 1 comes next; a product the customer gave no day of their own starts at attempt 1.
    out = run_facts(wf, dict(base, named_day_words="the 30th", dated_products="all"))
    assert json.loads(out["own_offer_products"]) == ["p1", "p2", "p3"] and out["dated_products"] == "none"
    out = run_facts(wf, dict(out, refused_products="personal loan", proposed_products="personal loan"))
    assert json.loads(out["refusal_counts"]) == {"p2": 1}
    out = run_facts(wf, dict(base, named_day_words="today", dated_products="the credit card"))
    out = run_facts(wf, dict(out, refused_products="personal loan", proposed_products="none"))
    assert json.loads(out["refusal_counts"]) == {"p2": 2}
    # The first answer that names a day for one product and refuses the others counts the first ask for those.
    out = run_facts(wf, dict(base, named_day_words="tomorrow", dated_products="credit card", refused_products="personal loan, car loan", proposed_products="all"))
    assert json.loads(out["refusal_counts"]) == {"p2": 1, "p3": 1}


def test_facts_read_products_flattened_under_the_node_name():
    # Seen live: the api_request result is flattened as load_account_response.data.products.N.field and
    # the response_mapping variable is absent.
    wf = compile_workflow(SPEC, API, BRIEFS)
    flat = {"now": "2026-10-21T09:00", "load_account_response.data.ok": True,
            "load_account_response.data.products.0.product_id": "p1", "load_account_response.data.products.0.type": "credit_card",
            "load_account_response.data.products.0.card_last4": "1234", "load_account_response.data.products.0.past_due": 300,
            "load_account_response.data.products.0.days_late": 4, "load_account_response.data.products.0.minimum_payment": 90,
            "load_account_response.data.products.1.product_id": "p2", "load_account_response.data.products.1.type": "credit_card",
            "load_account_response.data.products.1.card_last4": "5678", "load_account_response.data.products.1.past_due": 200,
            "load_account_response.data.products.1.days_late": 2, "load_account_response.data.products.1.minimum_payment": 60,
            "other_response.data.products.0.product_id": "x"}
    out = run_facts(wf, flat)
    assert out["facts_state"] == "ready" and out["product_count"] == "2"
    assert "product_id p1: credit card ending 1234" in out["account_facts"]
    assert "product_id p2: credit card ending 5678" in out["account_facts"]
    assert "on or before the deadline of p1, p2" in out["date_facts"]


def test_named_closed_day_carries_the_policy_action_only_within_the_deadline():
    spec = json.loads(json.dumps(SPEC))
    spec["calendar"]["closed_day_rule"] = "Offer the next business day"
    wf = compile_workflow(spec, API, BRIEFS)
    products = [{"product_id": "p1", "type": "credit_card", "card_last4": "1234", "past_due": 300.0, "days_late": 4, "minimum_payment": 90.0}]
    base = {"now": "2026-10-21T09:00", "account_products": json.dumps(products)}
    out = run_facts(wf, dict(base, named_day_words="Monday the twenty sixth"))
    assert "For this the policy says to offer the next business day: 2026-10-27 (Tuesday, 27 October 2026)" in out["named_day_facts"]
    out = run_facts(wf, dict(base, named_day_words="Saturday the 7th of November"))
    assert "AFTER the deadline of p1" in out["named_day_facts"] and "policy says" not in out["named_day_facts"]
    out = run_facts(wf, dict(base, named_day_words="Tuesday the 27th"))
    assert "policy says" not in out["named_day_facts"]


def test_stop_names_the_next_step():
    # PUB-12 as seen live: card for tomorrow, loans refused; after the car loan's STOP the model offered its floor.
    spec = json.loads(json.dumps(SPEC))
    step1 = "attempt 1: propose <last_business_day_this_week> for <amount>"
    spec["account"]["bands"] = [
        {"name": "early", "min": 1, "max": 10, "deadline": {"type": "business_days_after_today", "count": 5, "date": ""},
         "persuasion_attempts": 1, "attempt_plan": [step1]},
        {"name": "late", "min": 11, "max": 45, "deadline": {"type": "business_days_after_today", "count": 7, "date": ""},
         "persuasion_attempts": 2, "attempt_plan": [step1, "attempt 2: propose <floor> on <deadline>"]}]
    wf = compile_workflow(spec, API, BRIEFS)
    products = [{"product_id": "p1", "type": "credit_card", "card_last4": "9015", "past_due": 510.0, "days_late": 16, "minimum_payment": 153.0},
                {"product_id": "p2", "type": "personal_loan", "past_due": 1320.0, "days_late": 16, "instalment_amount": 440.0},
                {"product_id": "p3", "type": "car_loan", "past_due": 140.0, "days_late": 7, "instalment_amount": 46.0}]
    base = {"now": "2026-10-14T11:00", "account_products": json.dumps(products)}
    out = run_facts(wf, dict(base, named_day_words="tomorrow", dated_products="credit card", refused_products="personal loan, car loan", proposed_products="all"))
    assert "p1 credit card ending 9015: refused 0 times; the customer gave a day or an amount for it" in out["plan_state"]
    assert "NEXT STEP" not in out["plan_state"]
    out = run_facts(wf, dict(out, refused_products="personal loan", proposed_products="personal loan"))
    out = run_facts(wf, dict(out, refused_products="personal loan", proposed_products="personal loan"))
    assert json.loads(out["refusal_counts"]) == {"p2": 3, "p3": 1}
    # The personal loan is done and the car loan still has its attempt 1: that proposal is named.
    first = out["plan_state"].splitlines()
    assert first[0].startswith("The customer has just refused the last proposal allowed for p2 personal loan.")
    assert first[1].startswith("NEXT STEP: your next message makes exactly this proposal and no other: p3 car loan: attempt 1: propose")
    # From its STOP on, a finished product's deadline leaves the date facts, also while another product is still negotiated.
    assert "deadline of p2" not in out["date_facts"] and "deadline of p3" in out["date_facts"] and "Deadlines computed from today" not in out["date_facts"]
    out = run_facts(wf, dict(out, refused_products="car loan", proposed_products="car loan"))
    assert json.loads(out["refusal_counts"]) == {"p2": 3, "p3": 2}
    first = out["plan_state"].splitlines()
    assert first[0].startswith("The customer has just refused the last proposal allowed for p3 car loan.")
    assert first[1] == ("NEXT STEP: no product has a proposal left. Your next message is the read-back for p1 credit card ending 9015: the day the"
                        " customer gave, 2026-10-15 (Thursday, 15 October 2026) (calendar: 2026-10-15 Thursday: business day; on or before the deadline"
                        " of p1), and the amount owed now, 510, unless the customer named another amount. Ask them to confirm it as the policy"
                        " says. The read-back is the only amount and the only day in the message; nothing is proposed for any other product.")
    # The closing node takes over: it is routed to from check_date and shows no persuasion plan.
    assert out["negotiation_done"] == "yes"
    assert "p3 car loan: DONE" in out["wrap_up_facts"] and "p1 credit card ending 9015 (amount owed now 510; deadline " in out["wrap_up_facts"]
    assert out["wrap_up_facts"].splitlines()[-1].startswith("NEXT STEP: no product has a proposal left. Your next message is the read-back for p1")
    assert out["wrap_up_step"] == out["wrap_up_facts"].splitlines()[-1]
    # The closing phase shows no figure of a finished product: no floor, no band table, no deadline of p2 or p3 in the calendar.
    task = wf["nodes"]["wrap_up"]["task_message"]
    for k, v in out.items():
        task = task.replace("{{" + k + "}}", str(v))
    assert "46" not in task and "440" not in task and "153" not in task and "2 November" not in task
    assert "Deadlines computed from today" not in out["date_facts"] and "deadline of p3" not in out["date_facts"]
    assert "deadline of p1" in out["date_facts"]
    assert wf["nodes"]["wrap_up"]["on_enter"] == {"type": "llm", "prompt": "Reply to the customer now, doing exactly the NEXT STEP at the end of your task: {{wrap_up_step}}"}
    assert "PERSUASION PLAN" not in wf["nodes"]["wrap_up"]["task_message"] and "{{account_facts}}" not in wf["nodes"]["wrap_up"]["task_message"]
    assert wf["nodes"]["wrap_up"]["task_message"].rstrip().endswith("{{wrap_up_facts}}")
    route = wf["nodes"]["check_date"]["transitions"]
    assert route[0]["target_node"] == "wrap_up" and route[-1] == {"target_node": "negotiate", "description": "always", "condition": {"operator": "always"}}
    assert route[0]["condition"] == {"logic": "or", "conditions": [{"variable": "negotiation_done", "operator": "equals", "operand": "yes"}]}
    bad = json.loads(json.dumps(wf))
    bad["nodes"]["check_date"]["transitions"][0]["condition"]["logic"] = "and"
    assert any("top-level logic must be or" in issue for issue in validate_workflow(bad, API))
    # workflow-format.md: a top-level group other than "or" fails silently, so no conditional transition may use one.
    groups = [item["condition"] for _, item in walk(wf) if isinstance(item.get("condition"), dict) and "conditions" in item["condition"]]
    assert groups and all(g["logic"] == "or" for g in groups) and validate_workflow(wf, API) == []
    # The closing node keeps the extraction and the route through check_date, so a re-opened date is still checked and counted.
    assert wf["nodes"]["wrap_up"]["extraction_schema"] == wf["nodes"]["negotiate"]["extraction_schema"]
    assert wf["nodes"]["wrap_up"]["transitions"] == wf["nodes"]["negotiate"]["transitions"]
    # The step stays while nothing is left to propose, also on a later turn that names a day.
    out = run_facts(wf, dict(out, named_day_words="Thursday"))
    assert out["plan_state"].startswith("NEXT STEP: no product has a proposal left.")
    # A product nobody has answered for yet is not done: no closing step then.
    out = run_facts(wf, dict(base, refusal_counts=json.dumps({"p2": 2}), refused_products="personal loan", proposed_products="personal loan"))
    assert "NEXT STEP" not in out["plan_state"] and "STOP" in out["plan_state"] and out["negotiation_done"] == "no"
    # Every product refused to its STOP: the negotiate node closes as it does live (passed there); no read-back.
    out = run_facts(wf, dict(base, refusal_counts=json.dumps({"p1": 3, "p2": 3, "p3": 1}), refused_products="car loan", proposed_products="car loan"))
    assert out["negotiation_done"] == "no" and "read-back" not in out["plan_state"]
    assert ("NEXT STEP: no product has a proposal left. Your next message proposes no amount and no date: apply the policy for the products"
            " without a promise, then close the call.") in out["plan_state"]
    # One product keeps today's flow: no closing node routing.
    out = run_facts(wf, {"now": "2026-10-14T11:00", "account_products": json.dumps(products[:1]), "refused_products": "credit card"})
    assert out["negotiation_done"] == "no"


def test_a_day_named_with_a_partial_refusal_is_an_offer_for_the_other_products():
    # PUB-12's first answer with the dated_products extraction missing: the day still belongs to the product not refused,
    # so the closing node is reached when the loans are done.
    spec = json.loads(json.dumps(SPEC))
    step1 = "attempt 1: propose <last_business_day_this_week> for <amount>"
    spec["account"]["bands"] = [
        {"name": "early", "min": 1, "max": 10, "deadline": {"type": "business_days_after_today", "count": 5, "date": ""},
         "persuasion_attempts": 1, "attempt_plan": [step1]},
        {"name": "late", "min": 11, "max": 45, "deadline": {"type": "business_days_after_today", "count": 7, "date": ""},
         "persuasion_attempts": 2, "attempt_plan": [step1, "attempt 2: propose <floor> on <deadline>"]}]
    wf = compile_workflow(spec, API, BRIEFS)
    products = [{"product_id": "p1", "type": "credit_card", "card_last4": "9015", "past_due": 510.0, "days_late": 16, "minimum_payment": 153.0},
                {"product_id": "p2", "type": "personal_loan", "past_due": 1320.0, "days_late": 16, "instalment_amount": 440.0},
                {"product_id": "p3", "type": "car_loan", "past_due": 140.0, "days_late": 7, "instalment_amount": 46.0}]
    base = {"now": "2026-10-14T11:00", "account_products": json.dumps(products)}
    out = run_facts(wf, dict(base, named_day_words="tomorrow", refused_products="personal loan and car loan", proposed_products="all"))
    assert json.loads(out["own_offer_products"]) == ["p1"] and json.loads(out["own_offer_days"]) == {"p1": "2026-10-15"}
    # A refusal of everything with a day named is no offer; a day named after the first ask is not re-assigned.
    other = run_facts(wf, dict(base, named_day_words="Friday", refused_products="all", proposed_products="all"))
    assert json.loads(other["own_offer_products"]) == []
    out = run_facts(wf, dict(out, refused_products="personal loan", proposed_products="personal loan"))
    out = run_facts(wf, dict(out, refused_products="personal loan", proposed_products="personal loan"))
    out = run_facts(wf, dict(out, refused_products="car loan", proposed_products="car loan"))
    assert out["negotiation_done"] == "yes" and "p1 credit card ending 9015: the day the customer gave, 2026-10-15" in out["wrap_up_step"]
    # Before any product is finished the date facts are complete.
    early = run_facts(wf, dict(base, named_day_words="tomorrow", refused_products="personal loan and car loan", proposed_products="all"))
    assert "Deadlines computed from today" in early["date_facts"] and early["wrap_up_step"] == "Not in the closing phase."
    # "All" refused while a day is given for the card: the card is the customer's offer, not a refusal.
    mixed = run_facts(wf, dict(base, named_day_words="tomorrow", dated_products="credit card", refused_products="all", proposed_products="all"))
    assert json.loads(mixed["refusal_counts"]) == {"p2": 1, "p3": 1} and json.loads(mixed["own_offer_products"]) == ["p1"]
    # A pronoun refusal of a two-product proposal counts for both products proposed.
    both = run_facts(wf, dict(mixed, refused_products="those", proposed_products="personal loan and car loan"))
    assert json.loads(both["refusal_counts"]) == {"p2": 2, "p3": 2}


def test_a_day_the_policy_does_not_accept_is_not_read_back():
    # The customer's own day for the card is after its deadline: the loans' STOP does not close the call on that day.
    spec = json.loads(json.dumps(SPEC))
    step1 = "attempt 1: propose <last_business_day_this_week> for <amount>"
    spec["account"]["bands"] = [
        {"name": "early", "min": 1, "max": 10, "deadline": {"type": "business_days_after_today", "count": 5, "date": ""},
         "persuasion_attempts": 1, "attempt_plan": [step1]},
        {"name": "late", "min": 11, "max": 45, "deadline": {"type": "business_days_after_today", "count": 7, "date": ""},
         "persuasion_attempts": 2, "attempt_plan": [step1, "attempt 2: propose <floor> on <deadline>"]}]
    wf = compile_workflow(spec, API, BRIEFS)
    products = [{"product_id": "p1", "type": "credit_card", "card_last4": "9015", "past_due": 510.0, "days_late": 16, "minimum_payment": 153.0},
                {"product_id": "p2", "type": "personal_loan", "past_due": 1320.0, "days_late": 16, "instalment_amount": 440.0}]
    base = {"now": "2026-10-14T11:00", "account_products": json.dumps(products)}
    out = run_facts(wf, dict(base, named_day_words="30 October", dated_products="credit card", refused_products="personal loan", proposed_products="all"))
    assert json.loads(out["own_offer_days"]) == {"p1": "2026-10-30"}
    out = run_facts(wf, dict(out, refused_products="personal loan", proposed_products="personal loan"))
    out = run_facts(wf, dict(out, refused_products="personal loan", proposed_products="personal loan"))
    assert json.loads(out["refusal_counts"]) == {"p2": 3}
    assert out["negotiation_done"] == "no" and "is not accepted as it is" in out["plan_state"]


def test_a_tool_call_already_done_is_not_asked_for_again():
    # PUB-12 as seen live: the personal loan's note was written at its STOP, and the closing node wrote it again.
    spec = json.loads(json.dumps(SPEC))
    step1 = "attempt 1: propose <last_business_day_this_week> for <amount>"
    spec["account"]["bands"] = [
        {"name": "early", "min": 1, "max": 10, "deadline": {"type": "business_days_after_today", "count": 5, "date": ""},
         "persuasion_attempts": 1, "attempt_plan": [step1]},
        {"name": "late", "min": 11, "max": 45, "deadline": {"type": "business_days_after_today", "count": 7, "date": ""},
         "persuasion_attempts": 2, "attempt_plan": [step1, "attempt 2: propose <floor> on <deadline>"]}]
    wf = compile_workflow(spec, API, BRIEFS)
    products = [{"product_id": "p1", "type": "credit_card", "card_last4": "9015", "past_due": 510.0, "days_late": 16, "minimum_payment": 153.0},
                {"product_id": "p2", "type": "personal_loan", "past_due": 1320.0, "days_late": 16, "instalment_amount": 440.0},
                {"product_id": "p3", "type": "car_loan", "past_due": 140.0, "days_late": 7, "instalment_amount": 46.0}]
    base = {"now": "2026-10-14T11:00", "account_products": json.dumps(products)}
    out = run_facts(wf, dict(base, named_day_words="tomorrow", dated_products="credit card", refused_products="personal loan, car loan", proposed_products="all"))
    out = run_facts(wf, dict(out, refused_products="personal loan", proposed_products="personal loan"))
    out = run_facts(wf, dict(out, refused_products="personal loan", proposed_products="personal loan"))
    assert out["recorded_calls"] == "{}"
    # The engine's variable table after the note, as seen live: only the last call's arguments, flattened with dots.
    note = {"add_note_args.product_id": "p2", "add_note_args.reason": "refused", "add_note_response.status": "success",
            "add_note_response.data.ok": "true", "add_note_status_code": 200, "add_note_success_count": 1}
    out = run_facts(wf, dict(out, refused_products="car loan", proposed_products="car loan", **note))
    assert json.loads(out["recorded_calls"]) == {"p2": ["add_note"]}
    assert out["negotiation_done"] == "yes"
    rows = dict((line.split(":")[0], line) for line in out["wrap_up_facts"].splitlines())
    assert rows["p2 personal loan"].endswith("Already done for it in this call: add_note succeeded; do not call add_note for it again.")
    assert "Already done" not in rows["p3 car loan"]
    assert "Already done for it in this call: add_note succeeded" in out["account_facts"].split("\n")[2]
    assert "except a product whose line below says it is already done" in wf["nodes"]["wrap_up"]["task_message"]
    # A later call that failed adds nothing; what was recorded stays recorded.
    failed = {"add_note_args.product_id": "p3", "add_note_response.data.ok": "false", "add_note_status_code": 200}
    out = run_facts(wf, dict(out, **failed))
    assert json.loads(out["recorded_calls"]) == {"p2": ["add_note"]}
    # The card's promise recorded before the loans were done: the closing node does not read it back again.
    promise = {"create_promise_args.product_id": "p1", "create_promise_args.amount": 510, "create_promise_response.data.ok": "true",
               "create_promise_status_code": 200}
    out = run_facts(wf, dict(out, **promise))
    assert json.loads(out["recorded_calls"]) == {"p1": ["create_promise"], "p2": ["add_note"]}
    assert out["negotiation_done"] == "yes" and "read-back" not in out["wrap_up_step"]
    assert out["wrap_up_step"].startswith("NEXT STEP: no product has a proposal left and every promise the customer gave is recorded.")
    assert "p1 credit card ending 9015: its promise is already recorded" in out["wrap_up_facts"]
    # Nested, as the engine might hand it over: read as well.
    nested = run_facts(wf, dict(base, add_note_args={"product_id": "p3"}, add_note_response={"data": {"ok": True}}))
    assert json.loads(nested["recorded_calls"]) == {"p3": ["add_note"]}
