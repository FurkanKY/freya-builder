"""The facts code on an account read shaped like one credit card statement, for a Turkish agent: one object instead of a
product list, a deadline read from the product's own due date, one catch-all band, and neutral headers."""
import json
from pathlib import Path
from builder.compile import compile_workflow

ROOT = Path(__file__).resolve().parent.parent
API = json.loads((ROOT/"vendor/kit-v3/tools/openapi.json").read_text())
SPEC = json.loads((ROOT/"tests/fixtures/spec_sample.json").read_text())
BRIEFS = [{"path": "brief.md", "text": "brief"}]
NOW = "2026-10-14T11:00"  # a Wednesday
STATEMENT = {"statement_balance": 1250.0, "minimum_payment": 375.0, "due_date": "2026-10-20", "card_last4": "1234"}


def _spec(list_field="statement", band=None, **account):
    spec = json.loads(json.dumps(SPEC))
    spec["language"] = "Turkish"
    spec["account"] = dict({"list_field": list_field, "id_field": "statement_id", "type_field": "", "amount_field": "statement_balance",
                            "segment_field": "", "floor_field_by_type": "minimum_payment", "spoken_name_by_type": "kredi kartı <card_last4>",
                            "bands": [band or {"name": "ekstre", "deadline": {"type": "product_field", "field": "due_date"},
                                               "persuasion_attempts": 2, "attempt_plan": ["<amount> by <deadline>", "<floor> by <deadline>"]}]},
                           **account)
    return spec


def _run(spec, variables):
    wf = compile_workflow(spec, API, BRIEFS)
    code = wf["nodes"]["account_facts"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
    variables = dict({"now": NOW}, **variables)
    exec(compile(code, "facts", "exec"), {"vars": variables})
    return variables


def _flat(prefix, obj):
    return {prefix + "." + k: v for k, v in obj.items()}


def test_one_statement_object_at_the_list_path_is_the_one_product():
    spec = _spec()
    for variables in ({"account_products": json.dumps(STATEMENT)},
                      {"account_products": str(STATEMENT)},
                      # Seen live: the api_request result is flattened under the node name, here without a list index.
                      dict(_flat("load_account_response.data.statement", STATEMENT), **{"load_account_response.data.ok": True})):
        out = _run(spec, variables)
        assert out["facts_state"] == "ready" and out["product_count"] == "1", variables
        facts = out["account_facts"]
        # No id in the statement: it is named by its place, so the facts and a promise can name it.
        assert facts.startswith("Products, in the order the bank returned them:\n1. statement_id 1: kredi kartı 1234;"), facts
        assert "amount owed now (statement_balance) 1250" in facts and "floor (minimum_payment) 375" in facts
        assert "None" not in facts.split(". Raw:")[0]


def test_the_whole_data_object_is_the_one_product():
    spec = _spec(list_field="")
    data = dict(STATEMENT, ok=True)
    for variables in ({"account_products": json.dumps(data)}, _flat("load_account_response.data", data),
                      {"load_account_response.data": data}):
        out = _run(spec, variables)
        assert out["facts_state"] == "ready" and out["product_count"] == "1", variables
        assert "1. statement_id 1: kredi kartı 1234; amount owed now (statement_balance) 1250" in out["account_facts"]
    # A top-level array, as the mapped variable or flattened.
    two = [STATEMENT, dict(STATEMENT, card_last4="9876", statement_balance=80)]
    flat = dict(_flat("load_account_response.data.0", two[0]), **_flat("load_account_response.data.1", two[1]))
    for variables in ({"account_products": json.dumps(two)}, flat):
        out = _run(spec, variables)
        assert out["product_count"] == "2", variables
        assert "2. statement_id 2: kredi kartı 9876; amount owed now (statement_balance) 80" in out["account_facts"]
    # An error object holds no amount: it is no product.
    for variables in ({"account_products": json.dumps({"ok": False, "error": "not found"})},
                      _flat("load_account_response.data", {"ok": True, "products": []})):
        assert _run(spec, variables)["facts_state"] in ("no_products", "load_failed"), variables


def test_products_without_ids_in_a_list_are_numbered():
    out = _run(_spec(list_field="statements"), {"account_products": json.dumps([STATEMENT, dict(STATEMENT, card_last4="9876")])})
    assert "1. statement_id 1: kredi kartı 1234;" in out["account_facts"]
    assert "2. statement_id 2: kredi kartı 9876;" in out["account_facts"]
    assert out["product_count"] == "2"


def test_the_deadline_is_the_products_own_due_date():
    spec = _spec()
    for due in ("2026-10-20", "2026-10-20T00:00:00Z", "20.10.2026", "20/10/2026", "20 Ekim 2026", "20 EKİM 2026 Salı"):
        out = _run(spec, {"account_products": json.dumps(dict(STATEMENT, due_date=due))})
        facts = out["account_facts"]
        assert "deadline 2026-10-20 (Tuesday, 20 October 2026)" in facts, due
        assert "attempt 1: 1250 by 2026-10-20 (Tuesday" in facts and "attempt 2: 375 by 2026-10-20 (Tuesday" in facts, due
        assert "Band ekstre" in out["date_facts"] and "deadline each product's due_date" in out["date_facts"]
        assert "2026-10-20 Tuesday: business day; on or before the deadline of 1" in out["date_facts"]
        assert "2026-10-21 Wednesday: business day; AFTER the deadline of 1" in out["date_facts"]
    # The named days are checked against it, in Turkish words.
    friday = _run(spec, {"account_products": json.dumps(STATEMENT), "named_day_words": "cuma"})["named_day_facts"]
    assert "2026-10-16 Friday: business day; on or before the deadline of 1" in friday
    later = _run(spec, {"account_products": json.dumps(STATEMENT), "named_day_words": "haftaya cuma"})["named_day_facts"]
    assert "2026-10-23 Friday: business day; AFTER the deadline of 1 (1 deadline 2026-10-20 Tuesday)" in later


def test_a_due_date_on_a_closed_day_and_beyond_three_weeks():
    spec = _spec()
    # Sunday 18 October: the last business day before it, as for a fixed date.
    out = _run(spec, {"account_products": json.dumps(dict(STATEMENT, due_date="2026-10-18"))})
    assert "deadline 2026-10-16 (Friday, 16 October 2026)" in out["account_facts"]
    # The calendar reaches a deadline later than the usual three weeks.
    out = _run(spec, {"account_products": json.dumps(dict(STATEMENT, due_date="2026-11-12"))})
    assert "deadline 2026-11-12 (Thursday, 12 November 2026)" in out["account_facts"]
    assert "2026-11-12 Thursday: business day; on or before the deadline of 1" in out["date_facts"]


def test_a_missing_unreadable_or_past_due_date_gives_no_deadline():
    spec = _spec()
    for statement in (dict(STATEMENT, due_date=None), dict(STATEMENT, due_date="yakinda"), dict(STATEMENT, due_date="2026-10-05"),
                      {k: v for k, v in STATEMENT.items() if k != "due_date"}):
        out = _run(spec, {"account_products": json.dumps(statement), "named_day_words": "cuma"})
        assert out["facts_state"] == "ready", statement
        assert "deadline see policy" in out["account_facts"] and "attempt 1: 1250 by the deadline" in out["account_facts"]
        assert "deadline of" not in out["date_facts"] and "deadline of" not in out["named_day_facts"]
    # A band whose deadline names no field is a band without a deadline.
    out = _run(_spec(band={"name": "ekstre", "deadline": {"type": "product_field"}, "persuasion_attempts": 1}),
               {"account_products": json.dumps(STATEMENT)})
    assert out["facts_state"] == "ready" and "deadline see policy" in out["account_facts"]


def test_an_open_band_takes_a_product_without_the_segment_field():
    band = {"name": "hepsi", "deadline": {"type": "business_days_after_today", "count": 5}, "persuasion_attempts": 1}
    for segment, extra in (("", {}), ("days_late", {}), ("days_late", {"min": 0, "max": 1e9}), ("days_late", {"min": None, "max": None})):
        spec = _spec(band=dict(band, **extra), segment_field=segment)
        out = _run(spec, {"account_products": json.dumps(STATEMENT)})
        assert "; band hepsi; deadline 2026-10-21 (Wednesday, 21 October 2026); persuasion attempts 1" in out["account_facts"], (segment, extra)
        assert "days_late None" not in out["account_facts"]
    # A product before its due date ('days_late' -6) is in the open band too.
    out = _run(_spec(band=band, segment_field="days_late"), {"account_products": json.dumps(dict(STATEMENT, days_late=-6))})
    assert "; days_late -6; band hepsi;" in out["account_facts"]
    # A band with bounds still needs the segment value.
    out = _run(_spec(band=dict(band, min=1, max=30), segment_field="days_late"), {"account_products": json.dumps(STATEMENT)})
    assert "band hepsi" not in out["account_facts"] and out["facts_state"] == "ready"


def test_no_attempt_count_is_left_out():
    band = {"name": "ekstre", "deadline": {"type": "product_field", "field": "due_date"}}
    out = _run(_spec(band=band), {"account_products": json.dumps(STATEMENT)})
    assert "persuasion attempts" not in out["account_facts"] and "persuasion attempts" not in out["date_facts"]
    assert "; band ekstre; deadline 2026-10-20 (Tuesday, 20 October 2026); floor (minimum_payment) 375" in out["account_facts"]
    assert "Band ekstre (segment 0 to 1000000000): deadline each product's due_date." in out["date_facts"]
