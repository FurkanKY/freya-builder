import asyncio
import json
from pathlib import Path

import pytest

from builder import case
from builder.compile import _find

CONTRACT = {
    "openapi": "3.0.0",
    "servers": [{"url": "https://api.bank.example/v2"}],
    "paths": {
        "/musteri/{musteri_no}/dogrula": {"post": {"operationId": "kimlikDogrula", "requestBody": {"content": {"application/json": {
            "schema": {"type": "object", "properties": {"dogum_tarihi": {"type": "string"}}}}}}}},
        "/musteri/{musteri_no}/ekstre": {"get": {"operationId": "ekstreGetir"}},
        "/odeme-sozu": {"post": {"operationId": "close_call"}},
        "/gorusme-sonucu": {"post": {"operationId": "sonucKaydet"}},
        "/sms": {"post": {"operationId": "smsGonder"}},
    },
}


def test_operation_key_tolerates_server_prefix_and_trailing_slash():
    assert case.operation_key("GET /musteri/{musteri_no}/ekstre/", CONTRACT) == ("/musteri/{musteri_no}/ekstre", "get")
    assert case.operation_key("post /v2/odeme-sozu", CONTRACT) == ("/odeme-sozu", "post")
    assert case.operation_key("DELETE /odeme-sozu", CONTRACT) is None
    assert case.operation_key(None, CONTRACT) is None


def test_apply_roles_names_operations_and_moves_a_clashing_name_away():
    roles = {"verify_identity": "POST /musteri/{musteri_no}/dogrula", "get_account": "GET /musteri/{musteri_no}/ekstre",
             "create_promise": "POST /odeme-sozu", "close_call": "POST /gorusme-sonucu", "add_note": None}
    api = case.apply_roles(CONTRACT, roles)
    assert _find(api, "verify_identity") == ("/musteri/{musteri_no}/dogrula", "post")
    assert _find(api, "get_account") == ("/musteri/{musteri_no}/ekstre", "get")
    # The contract called its promise operation close_call; the role went elsewhere, so that name must not win.
    assert _find(api, "create_promise") == ("/odeme-sozu", "post")
    assert _find(api, "close_call") == ("/gorusme-sonucu", "post")
    assert _find(api, "add_note") == (None, None)
    assert api["paths"]["/odeme-sozu"]["post"]["x-contract-operation-id"] == "close_call"
    assert CONTRACT["paths"]["/odeme-sozu"]["post"]["operationId"] == "close_call"  # the input is not changed


def test_point_at_keeps_the_contract_prefix_only_for_a_bare_mock_url():
    api = json.loads(json.dumps(CONTRACT))
    assert case.point_at(api, "https://m.example.workers.dev")["servers"][0]["url"] == "https://m.example.workers.dev/v2"
    assert case.point_at(api, "https://m.example.workers.dev/x/")["servers"][0]["url"] == "https://m.example.workers.dev/x"
    with pytest.raises(ValueError):
        case.point_at(api, "m.example.workers.dev")


def test_role_and_document_issues():
    assert case.role_issues({"get_account": "GET /nope"}, CONTRACT)
    assert case.role_issues({"get_account": "GET /musteri/{musteri_no}/ekstre", "verify_identity": "GET /musteri/{musteri_no}/ekstre"}, CONTRACT)
    assert case.role_issues({"refund": None}, CONTRACT)
    assert not case.role_issues({"get_account": "GET /musteri/{musteri_no}/ekstre", "add_note": None}, CONTRACT)
    assert case.document_issues([{"path": "BRIEF.md", "agent_needs": False}], {"BRIEF.md"})
    assert case.document_issues([{"path": "x.md", "agent_needs": True}], {"BRIEF.md"})
    assert not case.document_issues([{"path": "BRIEF.md", "agent_needs": True}], {"BRIEF.md"})


def test_supplied_openapi_is_found_among_json_documents():
    docs = [{"path": "data.json", "kind": "json", "text": "[1, 2]"},
            {"path": "api.json", "kind": "json", "text": json.dumps(CONTRACT)}]
    assert case.supplied_openapi(docs) == ("api.json", CONTRACT)
    assert case.supplied_openapi(docs[:1]) == (None, None)


class Trace:
    def __init__(self):
        self.events = []

    def emit(self, event, **data):
        self.events.append((event, data))


def test_read_case_from_a_prose_contract(tmp_path):
    folder = tmp_path / "Case"
    folder.mkdir()
    (folder / "BRIEF.md").write_text("Arama kuralları.")
    (folder / "sozlesme.md").write_text("POST /musteri/{musteri_no}/dogrula ...")
    (folder / "musteriler.csv").write_text("musteri_no,ad\n1,Ali\n")
    answer = {"documents": [{"path": "BRIEF.md", "role": "brief", "agent_needs": True},
                            {"path": "sozlesme.md", "role": "contract", "agent_needs": False},
                            {"path": "musteriler.csv", "role": "test_data", "agent_needs": False}],
              "openapi": CONTRACT,
              "roles": {"verify_identity": "POST /musteri/{musteri_no}/dogrula", "get_account": "GET /musteri/{musteri_no}/ekstre",
                        "create_promise": "POST /odeme-sozu", "close_call": "POST /gorusme-sonucu", "add_note": None,
                        "schedule_callback": None, "transfer_to_agent": None},
              "notes": "Tarihler YYYY-MM-DD."}
    calls = []

    async def ask(prompt, purpose, system):
        calls.append((purpose, system))
        return "```json\n" + json.dumps(answer) + "\n```"

    work = tmp_path / "work"
    work.mkdir()
    trace = Trace()
    inputs = asyncio.run(case.read_case([folder], "https://m.example.workers.dev", work, ask, trace))
    assert len(calls) == 1 and calls[0][1] == case.CONTRACT_SYSTEM
    assert [d["path"] for d in inputs["briefs"]][0] == "BRIEF.md"
    assert [d["path"] for d in inputs["policy"]] == ["BRIEF.md"]
    assert inputs["api"]["servers"][0]["url"] == "https://m.example.workers.dev/v2"
    assert set(inputs["roles"]) == {"verify_identity", "get_account", "create_promise", "close_call"}
    assert inputs["contract_notes"] == "Tarihler YYYY-MM-DD."
    assert (work / "openapi.json").exists()
    read = dict(trace.events)["case_read"]
    assert read["unmapped_operations"] == ["POST /sms"]


def test_read_case_retries_once_and_keeps_the_better_answer(tmp_path):
    folder = tmp_path / "Case"
    folder.mkdir()
    (folder / "BRIEF.md").write_text("Kurallar.")
    good = {"documents": [{"path": "BRIEF.md", "agent_needs": True}], "openapi": CONTRACT,
            "roles": {"get_account": "GET /musteri/{musteri_no}/ekstre"}}
    answers = ["not json at all", json.dumps(good)]

    async def ask(prompt, purpose, system):
        return answers.pop(0)

    work = tmp_path / "work"
    work.mkdir()
    inputs = asyncio.run(case.read_case([folder], "https://m.example.workers.dev", work, ask, Trace()))
    assert inputs["roles"] == {"get_account": "GET /musteri/{musteri_no}/ekstre"}
    assert not answers


def test_read_case_without_a_usable_contract_stops(tmp_path):
    folder = tmp_path / "Case"
    folder.mkdir()
    (folder / "BRIEF.md").write_text("Kurallar.")

    async def ask(prompt, purpose, system):
        return json.dumps({"documents": [{"path": "BRIEF.md", "agent_needs": True}], "roles": {}})

    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(ValueError, match="No usable service contract"):
        asyncio.run(case.read_case([folder], "https://m.example.workers.dev", work, ask, Trace()))


def test_operations_no_role_maps_get_unique_tool_names():
    from builder.compile import TOOL_NAMES, compile_workflow, extra_tools
    from builder.runtime import validate_workflow
    contract = json.loads(json.dumps(CONTRACT))
    contract["paths"]["/notlar"] = {"post": {"operationId": "add_note", "summary": "Not ekler."}}
    contract["paths"]["/sms/toplu"] = {"post": {"summary": "Toplu SMS."}}
    contract["paths"]["/odeme/linki"] = {"post": {"operationId": "ödemeLinkiGönder"}}
    contract["paths"]["/close_call"] = {"post": {}}
    roles = {"verify_identity": "POST /musteri/{musteri_no}/dogrula", "get_account": "GET /musteri/{musteri_no}/ekstre",
             "create_promise": "POST /odeme-sozu", "close_call": "POST /gorusme-sonucu", "add_note": None}
    api = case.apply_roles(contract, roles)
    ids = {f"{m} {p}": op.get("operationId") for p, item in api["paths"].items() for m, op in item.items()}
    assert ids["post /sms"] == "sms_gonder" and api["paths"]["/sms"]["post"]["x-contract-operation-id"] == "smsGonder"
    assert ids["post /odeme/linki"] == "odeme_linki_gonder"
    assert ids["post /sms/toplu"] == "toplu"
    # A role name the case did not map is no role: neither its operationId nor a path ending in it.
    assert ids["post /notlar"] == "post_notlar" and api["paths"]["/notlar"]["post"]["x-contract-operation-id"] == "add_note"
    assert ids["post /close_call"] == "post_close_call" and _find(api, "close_call") == ("/gorusme-sonucu", "post")
    assert _find(api, "add_note") == (None, None)
    extra = set(ids.values()) - set(TOOL_NAMES)
    assert len(extra) == len([v for v in ids.values() if v not in TOOL_NAMES]) and not extra & set(TOOL_NAMES)
    # The compiler names the same tools, so the spec reader's names and the workflow's agree; applying again keeps them.
    again = case.apply_roles(api, roles)
    assert set(extra_tools(api)) == extra and {f"{m} {p}": op.get("operationId") for p, item in again["paths"].items() for m, op in item.items()} == ids
    assert again["paths"]["/sms"]["post"]["x-contract-operation-id"] == "smsGonder"
    spec = json.loads((Path(__file__).resolve().parent / "fixtures/spec_sample.json").read_text())
    spec["call_variables"] += ["musteri_no"]
    api = case.point_at(api, "https://m.example.workers.dev")
    wf = compile_workflow(spec, api, [{"path": "BRIEF.md", "text": "Kurallar."}])
    assert validate_workflow(wf, api) == []
    names = {t["function"]["name"] for t in wf["nodes"]["negotiate"]["tools"]}
    assert extra <= names and "add_note" not in names and {"create_promise", "close_call"} <= names
    # A path parameter the contract does not declare is still one: here the call variable of its name fills it.
    url = wf["nodes"]["load_account"]["pre_actions"][0]["function"]["parameters"]["properties"]["url"]["default"]
    assert url == "https://m.example.workers.dev/v2/musteri/{{musteri_no}}/ekstre"


def test_null_keys_of_a_model_written_contract_are_dropped(tmp_path):
    from builder.compile import compile_workflow
    from builder.runtime import validate_workflow
    assert case.no_nulls({"a": None, "b": [{"c": None, "d": 1}, None], "e": {"f": None}}) == {"b": [{"d": 1}, None], "e": {}}
    contract = json.loads(json.dumps(CONTRACT))
    contract["paths"]["/musteri/{musteri_no}/ekstre"]["get"].update(requestBody=None, parameters=None)
    contract["paths"]["/gorusme-sonucu"]["post"]["requestBody"] = {"content": {"application/json": {"schema": {
        "type": "object", "properties": {"musteri_no": {"type": "string"}, "sonuc": {"type": "string", "enum": ["SOZ", "RET"]}}, "required": None}}}}
    contract["paths"]["/sms"]["post"]["requestBody"] = {"content": {"application/json": {"schema": {"type": "object", "properties": None}}}}
    folder = tmp_path / "Case"
    folder.mkdir()
    (folder / "BRIEF.md").write_text("Kurallar.")
    answer = {"documents": [{"path": "BRIEF.md", "agent_needs": True}], "openapi": contract,
              "roles": {"verify_identity": "POST /musteri/{musteri_no}/dogrula", "get_account": "GET /musteri/{musteri_no}/ekstre",
                        "close_call": "POST /gorusme-sonucu"}}

    async def ask(prompt, purpose, system):
        return json.dumps(answer)

    work = tmp_path / "work"
    work.mkdir()
    api = asyncio.run(case.read_case([folder], "https://m.example.workers.dev", work, ask, Trace()))["api"]
    assert "requestBody" not in api["paths"]["/musteri/{musteri_no}/ekstre"]["get"]
    spec = json.loads((Path(__file__).resolve().parent / "fixtures/spec_sample.json").read_text())
    spec["call_variables"] += ["musteri_no"]
    wf = compile_workflow(spec, api, [{"path": "BRIEF.md", "text": "Kurallar."}])
    assert validate_workflow(wf, api) == []
    close = next(t for t in wf["nodes"]["negotiate"]["tools"] if t["function"]["name"] == "close_call")
    assert close["function"]["parameters"]["properties"]["body"]["required"] == []


def test_a_turkish_letter_before_a_capital_still_splits_the_name():
    from builder.compile import _tool_base
    assert [_tool_base(n) for n in ("borçSorgula", "ödemeLinkiGönder", "İadeTalebi")] == ["borc_sorgula", "odeme_linki_gonder", "iade_talebi"]
