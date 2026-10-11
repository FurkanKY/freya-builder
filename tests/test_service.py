import asyncio
import json
import re

from builder import case, service
from builder.runtime import Budget, validate_workflow

CONTRACT = {
    "openapi": "3.0.0",
    "servers": [{"url": "https://api.bank.example/v1"}],
    "paths": {
        "/customers/{customerNumber}/cards": {"get": {"operationId": "listCards", "summary": "The customer's cards",
            "responses": {"200": {"content": {"application/json": {"schema": {"type": "object", "properties": {"cards": {"type": "array", "items": {
                "type": "object", "properties": {"cardId": {"type": "string"}, "cardName": {"type": "string"}, "last4": {"type": "string"}}}}}}}}},
                "404": {"description": "customer not found"}}}},
        "/cards/{cardId}/statement": {"get": {"operationId": "getStatement", "summary": "The card's statement debt",
            "responses": {"200": {"content": {"application/json": {"schema": {"type": "object", "properties": {
                "totalDebt": {"type": "number"}, "dueDate": {"type": "string", "format": "date"}}}}}}}}},
        "/cards/{cardId}/statement-date": {"post": {"operationId": "changeStatementDate", "requestBody": {"content": {"application/json": {"schema": {
            "type": "object", "properties": {"customerNumber": {"type": "string"}, "newWeek": {"type": "string", "format": "date"}},
            "required": ["customerNumber", "newWeek"]}}}}, "responses": {"200": {}, "409": {"description": "already changed this year"}}}},
        "/transfers": {"post": {"operationId": "transferToAgent", "requestBody": {"content": {"application/json": {"schema": {
            "type": "object", "properties": {"customerNumber": {"type": "string"}, "reason": {"type": "string", "enum": ["PAY", "PERSON"]}}}}}}}},
    },
}
ROLES = {"get_account": "GET /cards/{cardId}/statement", "transfer_to_agent": "POST /transfers"}
SPEC = {
    "language": "Turkish", "call_variables": ["customerNumber", "now"], "now_variable": "now",
    "opening_line": "Merhaba, size nasıl yardımcı olabilirim?",
    "script": ["Call list_cards.", "If more than one card, name them and ask which one.", "Call get_statement with the card's cardId."],
    "rules": "1. Never read field names.\n2. On 409 from change_statement_date say it was already changed.",
    "tools": {"list_cards": "First, with no fields.", "get_statement": "cardId from list_cards."},
    "handoffs": "Payment or a person: call transfer_to_agent with reason PAY or PERSON, then end the call.",
    "closing": "İyi günler dileriz.",
    "test_variables": {"customerNumber": "10000001", "now": "2026-10-12T10:30:00+03:00"},
}


def _api():
    return case.point_at(case.apply_roles(CONTRACT, ROLES), "https://m.example.workers.dev")


def _urls(wf):
    return [t["function"]["parameters"]["properties"]["url"]["default"] for t in wf["nodes"]["serve"]["tools"]]


def test_the_call_kind_or_a_missing_promise_tool_makes_a_service_call():
    assert case.call_mode("inbound_service", {"create_promise": "POST /x"}) == "service"
    assert case.call_mode(None, ROLES) == "service"
    # A read that names no call kind keeps the collection agent where a promise tool is mapped.
    assert case.call_mode(None, {"create_promise": "POST /x"}) == "collection"
    assert case.call_mode("outbound_collection", {"create_promise": "POST /x"}) == "collection"
    # An explicit collection call stays on the collection path without a promise tool or with 'service' in its words.
    assert case.call_mode("outbound_collection", {}) == "collection"
    assert case.call_mode("outbound_collection: the collection service calls customers", ROLES) == "collection"


def test_service_tools_carry_the_contract_names_not_the_role_names():
    names = service.service_tools(_api())
    assert set(names) == {"list_cards", "get_statement", "change_statement_date", "transfer_to_agent"}
    text = service.operations_text(_api())
    assert "TOOL get_statement: GET /cards/{cardId}/statement" in text and "response 409 (already changed this year)" in text
    assert "cards[].last4: string" in text


def test_a_service_spec_compiles_to_a_valid_three_node_workflow():
    api = _api()
    wf = service.compile_service(SPEC, api, [{"path": "BRIEF.md", "text": "brief"}])
    assert validate_workflow(wf, api) == []
    assert set(wf["nodes"]) == {"prepare", "serve", "hang_up"} and wf["initial_node"] == "prepare"
    serve = wf["nodes"]["serve"]
    assert serve["on_enter"] == {"type": "tts", "text": SPEC["opening_line"]} and serve["on_enter_first_entry_only"] is True
    assert serve["transitions"][0]["target_node"] == "hang_up" and serve["max_turn_transition"] == "hang_up"
    for part in ("SCRIPT:\n1. Call list_cards.", "RULES:", "HANDOFFS:", "CLOSING:", "- customerNumber: {{customerNumber}}", "DATE FACTS:\n{{date_facts}}"):
        assert part in serve["task_message"], part
    assert "{{now}}" not in serve["task_message"]
    urls = _urls(wf)
    assert "https://m.example.workers.dev/v1/customers/{{customerNumber}}/cards" in urls
    # The call gives the customer number: it is never a field the model fills, nor a single-brace leftover.
    assert all("{customerNumber}" not in re.sub(r"\{\{\w+\}\}", "", u) for u in urls)
    change = next(t for t in serve["tools"] if t["function"]["name"] == "change_statement_date")["function"]["parameters"]["properties"]["body"]
    assert change["properties"]["customerNumber"]["default"] == "{{customerNumber}}" and change["required"] == ["newWeek", "cardId"]
    assert "Say everything in Turkish" in wf["system_prompt"] and "brief" in wf["system_prompt"]
    assert wf["test_variables"] == SPEC["test_variables"]


def test_the_prepare_code_gives_date_facts_from_the_call_date_not_the_clock():
    wf = service.compile_service(SPEC, _api(), [])
    code = wf["nodes"]["prepare"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
    for now, first in (("2026-10-12T10:30:00+03:00", "Now: 2026-10-12 (Monday, 12 October 2026 = 12 Ekim 2026 Pazartesi) 10:30"),
                       ("15.10.2026 09:05", "Now: 2026-10-15 (Thursday, 15 October 2026")):
        variables = {"now": now, "customerNumber": "10000001"}
        exec(compile(code, "prepare", "exec"), {"vars": variables})
        facts = variables["date_facts"]
        assert facts.startswith(first), facts
    assert "This week: 2026-10-12 (Monday" in facts and "to 2026-10-18 (Sunday" in facts
    assert "Next week: 2026-10-19 (Monday" in facts and "Week 6 from now: 2026-11-23 (Monday" in facts


def test_spec_issues_name_unknown_tools_and_a_missing_clock_or_call_variable():
    api = _api()
    assert service.spec_issues(SPEC, api) == []
    bad = dict(SPEC, tools={"getStatement": "x"}, call_variables=["now"], script="")
    issues = service.spec_issues(bad, api, [{"role": "readme", "text": "The call passes customerNumber and now."}])
    assert any(i.startswith("script") for i in issues)
    assert any("tools.getStatement" in i for i in issues)
    assert any("path parameter customerNumber" in i for i in issues)
    assert any("now_variable" in i for i in service.spec_issues(dict(SPEC, now_variable="today"), api))


class Trace:
    secrets = []

    def __init__(self):
        self.events = []

    def emit(self, event, **data):
        self.events.append((event, data))


def test_generate_service_fixes_a_bad_read_once(tmp_path, monkeypatch):
    answers = [json.dumps(dict(SPEC, tools={"nope": "x"})), "```json\n" + json.dumps(SPEC) + "\n```"]
    prompts = []

    async def ask(prompt, trace, model, cwd, purpose, budget, timeout=600, system=None):
        prompts.append(prompt)
        return answers.pop(0)

    monkeypatch.setattr(service, "ask_model", ask)
    inputs = {"briefs": [{"path": "BRIEF.md", "text": "brief", "role": "brief"}, {"path": "t.json", "text": "x" * 20000, "role": "test_data"}],
              "api": _api(), "contract_notes": "Dates YYYY-MM-DD."}
    trace = Trace()
    out = asyncio.run(service.generate_service(inputs, None, Budget(1800), trace, "m", tmp_path))
    assert not answers and "ITS ERRORS" in prompts[1] and "tools.nope" in prompts[1]
    assert len(prompts[0]) < 15000 and "CONTRACT NOTES\nDates YYYY-MM-DD." in prompts[0]
    assert out["spec"]["tools"] == SPEC["tools"] and validate_workflow(out["workflow"], inputs["api"]) == []
    assert set(out) == {"spec", "workflow", "rules", "coverage"}
    assert [e for e, _ in trace.events].count("service_read") == 2 and (tmp_path / "service-response-2.txt").exists()


def test_a_tool_returned_id_and_a_raw_line_break_are_no_issues_but_an_unfilled_opening_slot_is():
    api = _api()
    told = [{"role": "brief", "text": "The agent asks which card; cardId comes from the card list. The call passes customerNumber."}]
    assert service.spec_issues(SPEC, api, told) == []
    issues = service.spec_issues(dict(SPEC, opening_line="Merhaba {{ad}}"), api)
    assert any("opening_line uses {{ad}}" in i for i in issues)
    assert service.parse_spec('{"script": "1. a\n2. b"}') == {"script": "1. a\n2. b"}


def test_the_serve_node_keeps_reasoning_off_and_dates_reach_back_and_ahead():
    wf = service.compile_service(SPEC, _api(), [])
    assert wf["nodes"]["serve"]["reasoning_override"] == service.NEGOTIATE_REASONING
    code = wf["nodes"]["prepare"]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]
    variables = {"now": "2026-10-12T10:30:00+03:00"}
    exec(compile(code, "prepare", "exec"), {"vars": variables})
    assert "2026-09-07 (Monday" in variables["date_facts"] and "2026-11-26 (Thursday" in variables["date_facts"]


def test_generate_service_falls_back_to_the_documents_when_no_read_is_usable(tmp_path, monkeypatch):
    inputs = {"briefs": [{"path": "BRIEF.md", "text": "The phone menu passes customerNumber and now. Pick the card by cardId.",
                          "role": "brief"}], "api": _api()}
    for answers in (["not json", "still not"], [TimeoutError("slow"), TimeoutError("slow")], ["not json", TimeoutError("slow")]):
        async def ask(prompt, trace, model, cwd, purpose, budget, timeout=600, system=None, answers=list(answers)):
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        monkeypatch.setattr(service, "ask_model", ask)
        trace = Trace()
        out = asyncio.run(service.generate_service(inputs, None, Budget(1800), trace, "m", tmp_path))
        assert "service_fallback" in [e for e, _ in trace.events]
        assert out["spec"]["call_variables"] == ["customerNumber", "now"]
        wf = out["workflow"]
        assert validate_workflow(wf, inputs["api"]) == [] and wf["nodes"]["serve"]["on_enter"]["type"] == "llm"
        assert "Pick the card by cardId." in wf["system_prompt"]


def test_an_opening_with_unfilled_slots_is_not_spoken_as_is_and_the_agent_starts_at_the_first_script_step():
    from builder.service import ENTRY_PROMPT, SERVICE_FRAME, TOOL_START, spoken_opening
    variables = ["customerNumber", "now"]
    assert spoken_opening("Hello, this is the bank.", variables) == "Hello, this is the bank."
    assert spoken_opening("Hello {{customerNumber}}.", variables) == "Hello {{customerNumber}}."
    for line in ["Your card ending <last4> owes …", "Which card? For example [card name].", "Total {amount}.", "Hello {{name}}."]:
        assert spoken_opening(line, variables) == ""
    # the entry turn cannot call tools: it only says the caller is being checked, and step 1 starts on their next message
    assert "Do not call, name or write any tool" in ENTRY_PROMPT
    assert "start at SCRIPT step 1 and call its tool" in TOOL_START
    assert "Never write a tool name, '_call'" in SERVICE_FRAME and "a turn ends only with a question" in SERVICE_FRAME
    # a text-only message ends the turn: the lookups a later question needs run before the figures are read
    assert "A message with no tool call ends your turn" in SERVICE_FRAME


def test_service_tools_wait_longer_than_the_collection_default_for_a_slow_answer():
    from builder.service import TOOL_TIMEOUT_MS
    assert TOOL_TIMEOUT_MS >= 25000
