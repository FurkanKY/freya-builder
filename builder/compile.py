"""Compile a brief-derived BankSpec into a Freya workflow with verified platform patterns.

Bank facts (fields, enums, calendar, bands, outcomes, policy text) come only from the spec and
the supplied OpenAPI. This module holds platform mechanics, never bank policy.
"""
import json
import os
from pathlib import Path

SNIPPETS = Path(__file__).resolve().parent / "snippets"

# Variables that are set before or during a call; a body field with one of these names would be baked.
RESERVED = {"customer_id", "first_name", "last_name", "title", "now", "date_facts", "account_facts", "facts_state", "product_count", "account_products"}

NEGOTIATE_REASONING = os.environ.get("BUILDER_AGENT_REASONING", "enabled")

TOOL_NAMES = ("verify_identity", "get_account", "create_promise", "add_note", "schedule_callback", "transfer_to_agent", "close_call")

# Generic agent mechanics; bank rules are appended from the spec and the raw briefs.
FRAME = """You are a phone agent speaking with a customer. Keep every turn to one or two short sentences. Ask one question at a time.
Follow the BANK POLICY below exactly. It is the only source of rules; never invent terms, figures, dates or reasons.
Tool use: when a rule says to call a tool, CALL the tool; saying you did it is not enough. Call at most one tool per message.
After every tool result, read its what_to_do_next field and either speak to the customer or call the next tool. Never end a turn with nothing.
Never say that something was recorded, scheduled or transferred unless that tool returned ok true. Before that, do not use words such as "noted", "recorded", "booked" or "set up"; say what you will do next instead.
When the customer asks about an offer you already made, answer only the question in one short sentence that names it as the offer already made (for example "That is the amount I mentioned.") and stop there: do not say again that you can offer it and do not ask for it again.
Callers sometimes speak in pieces. If the customer's message is cut off or incomplete (it stops mid-sentence, or is a lone number, word or part of a date or digits that does not answer your question on its own), it is not an answer yet: reply only with a very short prompt such as "Go on." and wait. Do not repeat your question, do not act on the fragment, and do not count it as a refusal or a non-answer. Join the pieces into one answer once it is complete. An answer that already has every part the question needs (a date with day, month and year; the full number of digits) is complete: use it at once, even if it is short or ends abruptly. Numbers said in words are complete as said: "nineteen ninety" is 1990 and "twenty one" is 21. Your reply to a fragment is never empty; say at least "Go on." Never send a tool an answer that is visibly incomplete (fewer digits than asked for, or a date without day, month or year); ask only for the missing part.
Some customers chat about their day before they answer. A message that only chats, with no answer and no refusal, is unfinished too: acknowledge it in a few words and ask the same question again. It is not a refusal, a decline or a non-answer; only words that evade or refuse the question count as those. If the same question stays unanswered this way three times in a row, apply the policy for a non-answer.
Every question that asks the customer to pay something is a payment proposal. Make only the proposals the policy lists, in its order, and count each one; never add a proposal of your own in between. A customer's answer that already refuses or accepts a product, also as part of a group such as "the loans" or "none of them", counts as that product's answer to the first ask: continue with that product's next PERSUASION PLAN step and never ask it again for today.
Use the computed DATE FACTS and ACCOUNT FACTS for every date, weekday, deadline, floor and amount; do not compute them yourself.
Send dates to tools as YYYY-MM-DD and amounts as plain numbers."""

# The phone model's thinking budget is small: a long private reasoning leaves no reply ("no speakable content").
BRIEF_THINKING = """Think briefly before each reply, in a few short lines at most: which product and step you are on, the matching line of ACCOUNT FACTS or DATE FACTS, and what to say or call. Do not restate the policy to yourself. Then always give the reply."""

CLOSE_RULE = """Ending the call: say the required closing words (thank the customer, goodbye) and call close_call in that same message with the outcome and reason that the policy prescribes. close_call is always the very last tool call and is called exactly once."""


def _py_literal(text):
    # A JSON string is a valid Python literal; escaping braces keeps template markers out of the code.
    return json.dumps(text).replace("{", "\\x7b").replace("}", "\\x7d")


def _post_hook(tool, flag=None, answer_flag=None):
    lines = [
        "def _get(d, path):",
        "    for part in str(path).split('.'):",
        "        d = d.get(part) if isinstance(d, dict) else None",
        "    return d",
        "",
        "try:",
        "    if isinstance(result, dict):",
        "        result.pop('header', None)",
        "        d = result.get('data')",
        "        if not isinstance(d, dict):",
        "            d = dict()",
        "            result['data'] = d",
        # Banks name the success flag differently; without one, a reply with no error counts as success.
        "        ok = d.get('ok') if 'ok' in d else d.get('success') if 'success' in d else (not d.get('error'))",
        "        if ok is True or str(ok).lower() == 'true':",
    ]
    if tool == "verify_identity":
        lines += [
            f"            if str(_get(d, {flag!r})).lower() == 'true':",
            "                note = 'Identity is fully verified. Continue exactly as the policy says after verification.'",
            f"            elif str(_get(d, {(answer_flag or 'verified')!r})).lower() == 'true':",
            "                note = 'This answer is correct. Ask the next security question as the policy says.'",
            "            else:",
            "                note = 'This answer is NOT correct. Apply the policy for a wrong answer; wrong_answers_left shows what remains.'",
            "            if d.get('hint'):",
            "                note = note + ' The service returned hint ' + str(d.get('hint')) + '; apply the policy rule for it.'",
            "        else:",
            "            note = 'The service could not use this answer (ok false: ' + str(d.get('error') or 'no reason') + '). Ask the customer again; apply the policy.'",
        ]
    elif tool == "create_promise":
        lines += [
            "            note = 'The promise IS recorded. Tell the customer, then say what the policy requires after a recorded promise.'",
            "        else:",
            "            note = 'The promise was NOT recorded (' + str(d.get('error') or 'service error') + '). Never say it is recorded. Apply the policy for a failed recording.'",
        ]
    elif tool == "close_call":
        lines += [
            "            note = 'The call is closed. Say nothing more and call no tool.'",
            "        else:",
            "            note = 'close_call was refused (' + str(d.get('error') or 'error') + '). Correct the outcome or reason and call close_call again.'",
        ]
    else:
        lines += [
            f"            note = '{tool} succeeded. Speak to the customer now as the policy says, or call the next tool.'",
            "        else:",
            f"            note = '{tool} FAILED (' + str(d.get('error') or 'service error') + '). Do not claim it worked. Apply the policy for a failure.'",
        ]
    lines += [
        "        d['what_to_do_next'] = note",
        "except Exception:",
        "    pass",
        "",
    ]
    return "\n".join(lines)


def _leaf(schema, default, description=None):
    leaf = {"type": schema.get("type", "string"), "default": default}
    if schema.get("enum"):
        leaf["enum"] = list(schema["enum"])
    # Structured fields keep their shape so the model can fill them.
    if leaf["type"] in ("array", "object"):
        for key in ("items", "properties", "required"):
            if key in schema:
                leaf[key] = json.loads(json.dumps(schema[key]))
    # The API's own description (formats, units) comes first; the brief's hint adds to it.
    text = " ".join(t for t in (schema.get("description"), description) if t)
    if schema.get("enum"):
        text = (text + " " if text else "") + "One of: " + ", ".join(map(str, schema["enum"])) + "."
    if text:
        leaf["description"] = text
    return leaf


HTTP_METHODS = ("post", "put", "patch", "get", "delete")


def _method(api, tool):
    for path, item in api["paths"].items():
        if path.strip("/").split("/")[-1] == tool:
            return next((m for m in HTTP_METHODS if m in item), "post")
    return "post"


def operation(api, tool):
    for path, item in api["paths"].items():
        if path.strip("/").split("/")[-1] == tool:
            base = api["servers"][0]["url"].rstrip("/")
            return base + "/" + path.lstrip("/"), item[_method(api, tool)] if _method(api, tool) in item else next(iter(item.values()))
    raise ValueError(f"Tool API has no operation for {tool}")


def api_tool(api, tool, spec, description="", model_filled=True, max_retries=0):
    url, op = operation(api, tool)
    schema = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
    hints = (spec.get("tool_field_hints") or {}).get(tool, {})
    call_vars = set(spec.get("call_variables") or []) | {"customer_id"}
    reserved = RESERVED | call_vars
    body = {}
    for field, prop in schema.get("properties", {}).items():
        # In the identity check only identifiers are baked; anything else there is the caller's answer.
        identifier = field == "id" or field.endswith(("_id", "_ref")) or field == "customer_id"
        if field in call_vars and (tool != "verify_identity" or identifier):
            # Call identifiers such as customer_id are baked from the call variable of the same name.
            body[field] = {"type": prop.get("type", "string"), "default": "{{" + field + "}}"}
        elif model_filled:
            # A placeholder with no variable behind it leaves the field to the model (verified pattern).
            name = f"{tool}_{field}" if field in reserved else field
            body[field] = _leaf(prop, "{{" + name + "}}", hints.get(field))
        elif field in schema.get("required", []):
            # A code-run tool has no model to fill a required field; take the variable of the same name.
            body[field] = {"type": prop.get("type", "string"), "default": "{{" + field + "}}"}
    function = {
        "name": tool,
        "handler": "__function__:api_call",
        "description": description or op.get("summary") or tool,
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "default": url},
            "method": {"type": "string", "default": _method(api, tool).upper()},
            "connect_retries": {"type": "number", "default": 0 if max_retries == 0 else 2},
            "headers": {"type": "object", "properties": {"Content-Type": {"type": "string", "default": "application/json"}}},
            "body": {"type": "object", "properties": body, "required": [f for f in schema.get("required", []) if f not in call_vars]},
        }},
    }
    identity = spec.get("identity") or {}
    flag = identity.get("complete_flag") or "all_verified"
    tool_obj = {"type": "function", "config": {"timeoutMs": 12000, "maxRetries": max_retries}, "function": function,
                "post_process_code": _post_hook(tool, flag, identity.get("answer_flag"))}
    if tool == "close_call":
        silent = [o for o in (spec.get("outcomes") or {}).get("no_reason", []) if isinstance(o, str)]
        tool_obj["pre_process_code"] = (
            "try:\n    b = config.get('body')\n    if isinstance(b, dict):\n"
            "        r = str(b.get('reason') or '').strip()\n"
            f"        if b.get('outcome') in {json.dumps(silent)} or not r or r.startswith(chr(123)):\n"
            "            b.pop('reason', None)\nexcept Exception:\n    pass\n"
        )
    return tool_obj


def _true(variable):
    return [{"variable": variable, "operator": "equals", "operand": "true"}, {"variable": variable, "operator": "equals", "operand": "True"}]


def _closed_transition(target="hang_up"):
    return {"target_node": target, "description": "close_call succeeded", "condition": {"logic": "or", "conditions":
            [{"variable": "close_call_success_count", "operator": "greater_than", "operand": 0}]}}


def compile_workflow(spec, api, briefs):
    from .spec import normalize_spec, resolve_refs
    api = resolve_refs(api)
    spec = normalize_spec(spec, api)
    policy = spec.get("policy") or {}
    identity = spec.get("identity") or {}
    flag = identity.get("complete_flag") or "all_verified"
    raw = "\n\n".join(f"--- {d['path']} ---\n{d['text']}" for d in briefs)
    system_prompt = "\n\n".join(filter(None, [
        FRAME,
        "Language: " + str(spec.get("language") or "English") + ".",
        "BANK POLICY (verbatim documents, in the order given):\n" + raw,
        ("PRECEDENCE AND CLARIFICATIONS:\n" + policy["precedence"]) if policy.get("precedence") else "",
        CLOSE_RULE,
        ("CLOSING TABLE:\n" + policy["closing"]) if policy.get("closing") else "",
    ]))
    facts_code = "SPEC_JSON = " + _py_literal(json.dumps(spec, ensure_ascii=True)) + "\n" + (SNIPPETS / "facts.py").read_text()

    def code_node(name, target):
        return {"name": name, "node_type": "code", "passthrough": True, "passthrough_default_transition": target,
                "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True,
                "pre_actions": [{"type": "function", "function": {"name": "code_exec", "handler": "__function__:code_exec",
                                 "parameters": {"type": "object", "properties": {"code": {"type": "string", "default": facts_code},
                                                                                 "timeout_ms": {"type": "number", "default": 10000}}}}}],
                "transitions": [{"target_node": target, "description": "always", "condition": {"operator": "always"}}]}

    questions = "\n".join(f"- {q.get('field')}: {q.get('ask')} (send as: {q.get('answer_format')})" for q in identity.get("questions", []))
    identify_task = "\n\n".join(filter(None, [
        "PHASE: before identity verification. The account is not visible yet and must not be discussed.",
        policy.get("before_verification"),
        "Security questions, in order (verify_identity field value: question):\n" + questions if questions else "",
        "Call verify_identity once for each answer the customer gives, with the field of the question you asked.",
        "DATE FACTS:\n{{date_facts}}",
    ]))
    negotiate_task = "\n\n".join(filter(None, [
        "PHASE: identity is verified. The get_account result is in ACCOUNT FACTS.",
        BRIEF_THINKING,
        policy.get("after_verification"),
        "ACCOUNT FACTS:\n{{account_facts}}",
        "DATE FACTS:\n{{date_facts}}",
    ]))
    descriptions = spec.get("tool_descriptions") or {}
    pre_tools = [t for t in ("verify_identity", "schedule_callback", "transfer_to_agent", "close_call")]
    post_tools = [t for t in ("create_promise", "add_note", "schedule_callback", "transfer_to_agent", "close_call")]
    _, get_op = operation(api, "get_account")
    get_account = api_tool(api, "get_account", spec, model_filled=False, max_retries=2)
    get_account.pop("post_process_code")
    list_field = (spec.get("account") or {}).get("list_field") or "products"

    nodes = {
        "prepare": code_node("prepare", "identify"),
        "identify": {
            "name": "identify", "node_type": "conversation",
            "on_enter": {"type": "tts", "text": spec.get("opening_line") or "Hello."}, "on_enter_first_entry_only": True,
            "task_message": identify_task,
            "tools": [api_tool(api, t, spec, descriptions.get(t, "")) for t in pre_tools],
            "max_node_turns": 80, "max_turn_transition": "hang_up",
            "transitions": [
                {"target_node": "load_account", "description": "identity fully verified", "condition": {"logic": "or", "conditions": _true(f"verify_identity_response.data.{flag}")}},
                _closed_transition(),
            ],
        },
        "load_account": {
            "name": "load_account", "node_type": "api_request", "passthrough": True, "passthrough_default_transition": "account_facts",
            "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True, "suppress_tool_results": False,
            "pre_actions": [get_account],
            "response_mapping": [{"path": f"data.{list_field}", "variable": "account_products"}],
            "transitions": [{"target_node": "account_facts", "description": "always", "condition": {"operator": "always"}}],
        },
        "account_facts": code_node("account_facts", "negotiate"),
        "negotiate": {
            "name": "negotiate", "node_type": "conversation",
            "on_enter": {"type": "llm"}, "on_enter_first_entry_only": True,
            "task_message": negotiate_task,
            "tools": [api_tool(api, t, spec, descriptions.get(t, "")) for t in post_tools],
            "max_node_turns": 120, "max_turn_transition": "hang_up",
            # Multi-rule date, amount and per-product attempt decisions happen here.
            "reasoning_override": NEGOTIATE_REASONING,
            "transitions": [_closed_transition()],
        },
        "hang_up": {
            "name": "hang_up", "node_type": "end_call", "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True,
            "transitions": [],
            "terminal": {"type": "function", "function": {"name": "call_closed", "handler": "__function__:end_call",
                         "parameters": {"type": "object", "properties": {"message_mode": {"type": "string", "default": "none"}}}}},
        },
    }
    return {"initial_node": "prepare", "system_prompt": system_prompt, "global_nodes": {}, "nodes": nodes,
            "test_variables": spec.get("test_variables") or {}}
