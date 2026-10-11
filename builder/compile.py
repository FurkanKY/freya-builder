"""Compile a brief-derived BankSpec into a Freya workflow with verified platform patterns.

Bank facts (fields, enums, calendar, bands, outcomes, policy text) come only from the spec and
the supplied OpenAPI. This module holds platform mechanics, never bank policy.
"""
import ast
import io
import json
import re
import os
import tokenize
import urllib.parse
from pathlib import Path

SNIPPETS = Path(__file__).resolve().parent / "snippets"

# Variables that are set before or during a call; a body field with one of these names would be baked.
LOOSE = 0.35
RESERVED = {"customer_id", "first_name", "last_name", "title", "now", "date_facts", "account_facts", "facts_state", "product_count",
            "account_products", "named_day_words", "named_day_facts", "refused_products", "proposed_products", "dated_products", "own_offer_products", "refusal_counts", "plan_state",
            "negotiation_done", "wrap_up_facts", "wrap_up_step", "own_offer_days", "recorded_calls", "named_amount_words", "amount_named",
            "readback_said", "wrap_up_mode", "wrap_up_say", "asked_back", "first_ask_open", "first_ask_closed",
            "accepted_products", "agreed_products", "next_step", "plain_refusal", "proposed_amount", "proposal_mode", "proposal_say"}

# With reasoning the phone model sometimes thinks past its budget on multi-product turns and stays silent;
# without it, date and attempt decisions are moved into code (DATE FACTS, ACCOUNT FACTS, the named-day check).
NEGOTIATE_REASONING = os.environ.get("BUILDER_AGENT_REASONING", "disabled")
# A day the customer names is read by extraction and checked against the calendar in code before the reply.
DATE_CHECK = os.environ.get("BUILDER_DATE_CHECK", "on") != "off"
# The products the customer refuses are read by extraction and counted per product in code (PROPOSAL COUNT).
COUNT_CHECK = DATE_CHECK and os.environ.get("BUILDER_COUNT_CHECK", "on") != "off"

TOOL_NAMES = ("verify_identity", "get_account", "create_promise", "add_note", "schedule_callback", "transfer_to_agent", "close_call")

# Generic agent mechanics; bank rules are appended from the spec and the raw briefs.
FRAME = """You are a phone agent speaking with a customer. Keep every turn to one or two short sentences. Ask one question at a time.
Follow the BANK POLICY below exactly. It is the only source of rules; never invent terms, figures, dates or reasons.
Tool use: when a rule says to call a tool, CALL the tool; saying you did it is not enough. Call at most one tool per message.
After every tool result, read its what_to_do_next field and either speak to the customer or call the next tool. Never end a turn with nothing.
Never say that something was recorded, scheduled or transferred unless that tool returned ok true. Before that, do not use words such as "noted", "recorded", "booked" or "set up"; say what you will do next instead.
When the customer asks back why you need an answer, give the reason in one short sentence and stop there: do not repeat the question in that message, because each repeat counts as asking again.
When the customer asks about an offer you already made, answer only the question in one short sentence that names it as the offer already made (for example "That is the amount I mentioned.") and stop there: do not say again that you can offer it and do not ask for it again.
Callers sometimes speak in pieces. If the customer's message is cut off or incomplete (it stops mid-sentence, or is a lone number, word or part of a date or digits that does not answer your question on its own), it is not an answer yet: reply only with a very short prompt such as "Go on." and wait. Do not repeat your question, do not act on the fragment, and do not count it as a refusal or a non-answer. Join the pieces into one answer once it is complete. An answer that already has every part the question needs (a date with day, month and year; the full number of digits) is complete: use it at once, even if it is short, ends abruptly or is followed by a few cut-off words such as "This is"; never reply "Go on." to it. Numbers said in words are complete as said: "nineteen ninety" is 1990 and "twenty one" is 21. Your reply to a fragment is never empty; say at least "Go on." Say "Go on." at most once in a row: if the next message is cut off again, say "Sorry, I missed that, could you say it again?" and nothing else; it does not count as asking your question again. Never send a tool an answer that is visibly incomplete (fewer digits than asked for, or a date without day, month or year); ask only for the missing part.
Some customers chat about their day before they answer. A message that only chats, with no answer and no refusal, is unfinished too: acknowledge it in a few words and ask the same question again. It is not a refusal, a decline or a non-answer; only words that evade or refuse the question count as those. If the same question stays unanswered this way three times in a row, apply the policy for a non-answer.
A hardship the customer mentions (illness, a death in the family, job loss, or another the policy names) brings in the policy's rule for it, which comes before the PERSUASION PLAN for the rest of the call: from then on make only the proposals that rule allows, also when the customer then asks for more time or a smaller amount, and follow that rule to its end.
Every question that asks the customer to pay something is a payment proposal. Make only the proposals the policy lists, in its order, and count each one; never add a proposal of your own in between. A customer's answer that already refuses or accepts a product, also as part of a group such as "the loans" or "none of them", counts as that product's answer to the first ask: continue with that product's next PERSUASION PLAN step and never ask it again for today.
A refusal that rejects every proposal in advance ("whatever you offer", "not a cent", "don't bother") is still one refusal of the proposal just made: the product's next PERSUASION PLAN step follows, as the PROPOSAL COUNT says, unless an exception of the policy (such as hardship) applies.
Products can get different numbers of proposals. Give each product exactly the steps of its own PERSUASION PLAN, never the steps of another product; at its STOP the product is done: offer it nothing more, not its floor, a smaller amount or another date. When a PROPOSAL COUNT is given, it says which proposal comes next for each product; follow it.
When the customer names one date for several products and it is inside some products' deadlines but after another's, the date stays for the products it fits: say so in the same sentence in which you propose the earlier date for the other product, and read back each product with its own date.
Use the computed DATE FACTS, ACCOUNT FACTS and NAMED DAY CHECK for every date, weekday, deadline, floor and amount; do not compute them yourself. When the customer names a day, the NAMED DAY CHECK line says what that day is; apply the policy to it. A time named without a day ("this evening at half past seven", "at three") is on today's date, the date on the Now line of DATE FACTS.
Send dates to tools in the format the tool field or the security question states (YYYY-MM-DD when none is stated) and amounts as plain numbers. Say dates to the customer in words (weekday, day and month, such as "Friday, 16 October"), never as digits like 2026-10-16."""

# The phone model's thinking budget is small: a long private reasoning leaves no reply ("no speakable content").
BRIEF_THINKING = """Think briefly before each reply, in a few short lines at most: which product and step you are on, the matching line of ACCOUNT FACTS or DATE FACTS, and what to say or call. Do not restate the policy to yourself. Then always give the reply."""

CLOSE_RULE = """Ending the call: say the required closing words (thank the customer, goodbye) and call close_call in that same message with the outcome and reason that the policy prescribes. close_call is always the very last tool call and is called exactly once."""
# A bank without a closing tool: the model ends the call itself through a tool-call transition (workflow-format.md).
END_CALL = "End the call. Call it in the same message as the closing words, once nothing more is to be said or done."
CLOSE_RULE_NO_TOOL = """Ending the call: say the required closing words (thank the customer, goodbye), then end the call: call transition_to_hang_up in that same message. It is always the very last step. This bank has no tool that records the call's outcome: never say an outcome was recorded."""
# What the agent must not claim when the bank has no tool for a job; the policy may still describe the job.
NO_TOOL = {
    "create_promise": "This bank has no tool that records a payment promise: agree the promise in words and never say it was recorded.",
    "add_note": "This bank has no note tool: never say a note was made.",
    "schedule_callback": "This bank has no callback tool: never say a callback was booked.",
    "transfer_to_agent": "This bank has no transfer tool: never say the call is being transferred.",
}


# Seen live (Sunday 11:55): the platform's code_exec takes at most 131072 bytes of code and call data together. With the
# full facts.py and spec (94 KB) the check failed from the third negotiation turn on, and the plan stopped moving.
CODE_LIMIT = 131072
CODE_BUDGET = 72000          # the code's share: the rest is left for the call's variables, which grow with every turn
# The spec fields facts.py reads; the policy only for a confirmation question it quotes (same pattern as facts.py).
CODE_SPEC_FIELDS = ("language", "now_variable", "calendar", "account")
QUOTED_QUESTION = r"['\"\u201c\u2018]([A-Z][^'\"\u201c\u201d\u2018\u2019{}<>\n]{2,80}\?)['\"\u201d\u2019]"


def _no_docstrings(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if len(body) > 1 and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                node.body = body[1:]
    return ast.dump(tree)


def compact_code(src):
    """The source without comments, docstrings and blank lines, one space per indent level. Token text is kept as written,
    so the code runs where the source runs; when the result does not parse to the same program, the source is kept."""
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, SyntaxError):
        return src
    lines = src.split("\n")
    cut, gone, inside = dict(), set(), set()
    before = None
    for i, t in enumerate(toks):
        if t.type == tokenize.COMMENT:
            cut[t.start[0]] = t.start[1]
        elif t.type == tokenize.STRING:
            after = next((x for x in toks[i + 1:] if x.type not in (tokenize.NL, tokenize.COMMENT)), None)
            alone = before is None or before.type in (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT)
            if alone and after is not None and after.type in (tokenize.NEWLINE, tokenize.ENDMARKER):
                gone.update(range(t.start[0], t.end[0] + 1))
            else:
                inside.update(range(t.start[0] + 1, t.end[0] + 1))
        if t.type not in (tokenize.NL, tokenize.COMMENT):
            before = t
    out = []
    for row, line in enumerate(lines, 1):
        if row in gone:
            continue
        if row in inside:
            # A line of a string that spans lines is kept as written, up to a comment after the string's end.
            out.append(line[:cut[row]].rstrip() if row in cut else line)
            continue
        if row in cut:
            line = line[:cut[row]]
        line = line.rstrip()
        if not line.strip():
            continue
        lead = len(line) - len(line.lstrip(" "))
        out.append(" " * (lead // 4 + (lead % 4 > 0)) + line.lstrip(" "))
    small = "\n".join(out) + "\n"
    try:
        same = _no_docstrings(ast.parse(small)) == _no_docstrings(ast.parse(src))
    except SyntaxError:
        same = False
    return small if same else src


def code_spec(spec):
    """The part of the spec the code node reads."""
    part = {k: spec[k] for k in CODE_SPEC_FIELDS if k in spec}
    policy = spec.get("policy") if isinstance(spec.get("policy"), dict) else {}
    part["policy"] = {k: " ".join(m.group(0) for m in re.finditer(QUOTED_QUESTION, str(v or "")))
                      for k, v in policy.items() if re.search(QUOTED_QUESTION, str(v or ""))}
    return part


def _py_literal(text):
    # A JSON string is a valid Python literal; escaping braces keeps template markers out of the code.
    return json.dumps(text).replace("{", "\\x7b").replace("}", "\\x7d")


ANSWER_RIGHT = ["true", "1", "correct", "match", "matched", "pass", "passed", "valid", "verified", "yes", "ok", "success"]
ANSWER_WRONG = ["false", "0", "incorrect", "wrong", "no_match", "nomatch", "mismatch", "not_matched", "fail", "failed", "invalid", "no",
                "not_verified", "unverified"]


def _post_hook(tool, flag=None, answer_flag=None, complete_value=None, answer_value=None, max_wrong=None, one_call=False):
    right = sorted(set(ANSWER_RIGHT) | ({str(answer_value).lower()} if answer_value not in (None, "") else set()))
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
        "            d = dict(error=str(d)[:200]) if d not in (None, '') else dict()",
        "            result['data'] = d",
        # An HTTP error or a failed request is never a success, whatever the body says.
        "        code = result.get('status_code')",
        "        failed = str(result.get('status') or 'success').lower() != 'success' or (isinstance(code, int) and code >= 400)",
        "        if failed and not d.get('error'):",
        "            d['error'] = str(result.get('message') or code or 'request failed')[:200]",
        # Banks name the success flag differently; without one, a reply with no error counts as success.
        "        ok = False if failed else d.get('ok') if 'ok' in d else d.get('success') if 'success' in d else (not d.get('error'))",
        "        if ok is True or str(ok).lower() == 'true':",
    ]
    if tool == "verify_identity":
        lines += [
            f"            if str(_get(d, {flag!r})).lower() in {sorted({'true', str(complete_value).lower()} - {'none', ''})!r}:",
            "                note = 'Identity is fully verified. Continue exactly as the policy says after verification.'",
        ] + ([
            # All the answers in one request: anything short of the full check is a failed check.
            "            else:",
            "                note = " + _py_literal(
                "Identity is NOT verified: the service did not accept all the answers. Apply the policy for wrong answers (count"
                " them as the policy says); where it allows another try, ask again only what it allows and call verify_identity once"
                " more with all the answers."),
        ] if one_call else [
            # A per-answer result can be a boolean or a word (MATCH, correct); a value that is neither says nothing.
            f"            elif str(_get(d, {(answer_flag or 'verified')!r})).strip().lower() in {right!r}:",
            "                note = 'This answer is correct. Ask the next security question as the policy says.'",
            f"            elif str(_get(d, {(answer_flag or 'verified')!r})).strip().lower() in {sorted(set(ANSWER_WRONG) - set(right))!r}:",
            # The brief's own limit, not the service's: a held-out brief stopped at two wrong answers where the service allowed three.
            "                note = " + _py_literal(
                "This answer is NOT correct. The policy ends the security check after %d wrong answers in total, across all the"
                " questions: count them yourself (a retry the policy does not count, such as one after a hint, is not counted). A"
                " count of tries left in this response follows the service's own limit and never extends the policy's." % max_wrong
                if max_wrong else "This answer is NOT correct. Apply the policy for a wrong answer; count the wrong answers as the"
                " policy says."),
            "            else:",
            "                note = 'The service did not say whether this answer was correct, and identity is not verified yet. If the response shows fewer tries left than before, treat it as wrong; otherwise ask the next security question as the policy says.'",
        ]) + [
            "            if d.get('hint'):",
            "                note = note + ' The service returned hint ' + str(d.get('hint')) + '; apply the policy rule for it.'",
            # A failed request (the bank's 5xx) checked nothing: it is no wrong answer, and the same answer can be sent again.
            "        elif failed:",
            "            note = 'verify_identity FAILED (' + str(d.get('error') or 'service error')[:120] + '): the service did not check"
            " this answer, so it is neither right nor wrong and is not counted as a wrong answer. Apply the policy for a failed tool;"
            " where it says nothing, call verify_identity once more with the same " + ("answers" if one_call else "field and answer")
            + ", without asking the customer again.'",
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
# A case's API (case.apply_roles) carries this key: its tools are found by operationId only.
BY_OPERATION_ID = "x-tools-by-operation-id"
ASCII = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")


def _norm(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").lower()).strip("_")


def _tail(path):
    """The last path segment that is not a path parameter: /get_account/{customer_id} -> get_account."""
    parts = [x for x in path.strip("/").split("/") if x and not x.startswith("{")]
    return parts[-1] if parts else ""


def _find(api, tool):
    """The (path, method) of a tool: by operationId first (a case's role mapping), then path tail, then a normalised path
    tail (get-account). A case's API names its tools by operationId only: a path ending in a role word is no tool there."""
    paths = api["paths"]
    tests = [lambda p, op: _norm(op.get("operationId")) == tool]
    if not api.get(BY_OPERATION_ID):
        tests += [lambda p, op: _tail(p) == tool, lambda p, op: _norm(_tail(p)) == tool]
    for test in tests:
        for path, item in paths.items():
            for method in HTTP_METHODS:
                if isinstance(item, dict) and isinstance(item.get(method), dict) and test(path, item[method]):
                    return path, method
    return None, None


def _tool_base(name):
    """snake_case of an operation name: Turkish letters as ASCII, then camelCase split (borçSorgula -> borc_sorgula)."""
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(name or "").translate(ASCII))
    return _norm(name)[:48].strip("_")


def extra_tools(api):
    """{tool name: (path, method)} of the operations no built-in tool uses. The name comes from the operationId, else the path
    tail, else the method and path; it is never a built-in tool's name and each is used once. case.apply_roles writes it as
    the operationId."""
    roles = {_find(api, t) for t in TOOL_NAMES}
    names = {}
    for path, item in api["paths"].items():
        for method in HTTP_METHODS:
            op = item.get(method) if isinstance(item, dict) else None
            if not isinstance(op, dict) or (path, method) in roles:
                continue
            base = _tool_base(op.get("operationId") or op.get("x-contract-operation-id")) or _tool_base(_tail(path))
            if not base or base in TOOL_NAMES:
                base = _tool_base(method + " " + path)
            name, n = base, 1
            while name in TOOL_NAMES or name in names:
                n += 1
                name = f"{base}_{n}"
            names[name] = (path, method)
    return names


def _method(api, tool):
    return _find(api, tool)[1] or "post"


def operation(api, tool):
    path, method = _find(api, tool)
    if path is None:
        raise ValueError(f"Tool API has no operation for {tool}")
    return api["servers"][0]["url"].rstrip("/") + "/" + path.lstrip("/"), api["paths"][path][method]


def _body_schema(op):
    return (((op.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}


def _params(api, path, op):
    """The path, query and header parameters of an operation, the operation's own over its path's. A {name} in the path
    that no parameter declares is a required string path parameter."""
    found = {("path", n): {"name": n, "in": "path", "required": True, "schema": {"type": "string"}}
             for n in re.findall(r"\{([^{}/]+)\}", path)}
    for param in list((api["paths"].get(path) or {}).get("parameters") or []) + list(op.get("parameters") or []):
        if isinstance(param, dict) and param.get("name") and param.get("in") in ("path", "query", "header"):
            found[(param["in"], param["name"])] = param
    return found


def _enum_prop(props, name):
    """The request property holding the allowed values: the one called name, else the only enum property."""
    enums = [k for k, v in props.items() if isinstance(v, dict) and v.get("enum")]
    return name if name in enums else enums[0] if len(enums) == 1 else None


def _alike(name, variables):
    """The variable named like name but for case and separators (musteriNo, musteri_no)."""
    flat = _norm(name).replace("_", "")
    return next((v for v in sorted(variables) if _norm(v).replace("_", "") == flat), None)


def _call_vars(spec):
    """(every call variable, those a tool field may take). The clock or a variable named like a fact the agent settles (date,
    time, amount) is never baked into a tool field: a clock called 'date' would fix every promise date to the call's start."""
    from .spec import FACT_TOKENS
    named = set(spec.get("call_variables") or []) | {"customer_id"}
    return named, set(v for v in named if v != spec.get("now_variable") and str(v).lower() not in FACT_TOKENS)


def _per_answer(spec, props):
    """True when the identity request checks one answer per call: a field enum that names every question's field, or a body
    with neither a field of its own for each question (also inside an object field) nor a list of answers. Names are compared
    but for case and separators (dogum_tarihi, DOGUM_TARIHI, dogumTarihi)."""
    flat = lambda names: {_norm(n).replace("_", "") for n in names}
    enum = _enum_prop(props, "field")
    fields = flat(str(q.get("field")) for q in (spec.get("identity") or {}).get("questions") or [] if isinstance(q, dict))
    inner = [v for v in props.values() if isinstance(v, dict)]
    own = flat(props) | flat(k for v in inner for k in (v.get("properties") or {}))
    listed = any(v.get("type") == "array" for v in inner)
    return (enum is not None and fields <= flat(map(str, props[enum]["enum"]))) or not (fields <= own or listed)


def _engine_source(api, name, call_vars):
    """The variable an engine-run call (no model) takes a parameter from when no call variable has its name: a call
    variable of the same normalised name, else the identity check's response field or argument of that name."""
    same = _alike(name, call_vars)
    if same:
        return same
    path, method = _find(api, "verify_identity")
    if path is None:
        return None
    op = api["paths"][path][method]
    out = next((r for c, r in sorted((op.get("responses") or {}).items()) if str(c).startswith("2") and isinstance(r, dict)), {})
    out = (((out.get("content") or {}).get("application/json") or {}).get("schema") or {}).get("properties") or {}
    if name in out:
        return f"verify_identity_response.data.{name}"
    if name in (_body_schema(op).get("properties") or {}) or any(n == name for _, n in _params(api, path, op)):
        return f"verify_identity_args.{name}"
    return None


# Credentials are the mock's business: the compiler never sends an auth header the contract declares.
AUTH_HEADER = re.compile(r"auth|api[-_]?key|token|secret|cookie|signature|session|content-type|^accept$", re.I)


def _param_hook(moved):
    """Pre-hook: each (where, name, variable, keep) parameter takes the model's body field of its name (removed from the body
    unless the API's body has it too), else the variable, and goes into the URL path, the query or the headers."""
    return (
        "try:\n    import json, urllib.parse\n"
        f"    moved = json.loads({_py_literal(json.dumps(moved))})\n"
        "    env = vars if isinstance(vars, dict) else dict()\n"
        "    b = config.get('body')\n    b = b if isinstance(b, dict) else dict()\n"
        "    h = config.get('headers')\n    h = h if isinstance(h, dict) else dict()\n"
        "    u = str(config.get('url') or '')\n"
        "    for where, name, var, keep in moved:\n"
        "        v = b.get(name) if keep else b.pop(name, None)\n"
        "        if (v in (None, '') or str(v).startswith(chr(123))) and var:\n            v = env.get(var)\n"
        "        v = '' if v is None else str(v).strip()\n"
        "        if not v or v.startswith(chr(123)):\n            continue\n"
        "        if where == 'path':\n            q = urllib.parse.quote(v, safe='')\n"
        "            u = u.replace(chr(123) * 2 + name + chr(125) * 2, q).replace(chr(123) + name + chr(125), q)\n"
        "        elif where == 'query':\n            u = u + ('&' if '?' in u else '?') + urllib.parse.urlencode([(name, v)])\n"
        "        else:\n            h[name] = v\n"
        "    config['url'] = u\n    config['headers'] = h\nexcept Exception:\n    pass\n"
    )


def api_tool(api, tool, spec, description="", model_filled=True, max_retries=0, key=None):
    path, method = key or _find(api, tool)
    if path is None:
        raise ValueError(f"Tool API has no operation for {tool}")
    op = api["paths"][path][method]
    url = api["servers"][0]["url"].rstrip("/") + "/" + path.lstrip("/")
    schema = _body_schema(op)
    hints = (spec.get("tool_field_hints") or {}).get(tool, {})
    named, call_vars = _call_vars(spec)

    # The call variable a field or parameter takes: its own name, else one named like it (musteriNo, musteri_no).
    def alias(name):
        return name if name in call_vars else None if name in named else _alike(name, call_vars)
    # The customer key is whatever get_account needs from the call (customer_number, cif, ...), not only *_id or *_ref.
    keys = set()
    if tool == "verify_identity":
        get_path, get_method = _find(api, "get_account")
        if get_path is not None:
            get_op = api["paths"][get_path][get_method]
            keys = {alias(n) for n in set(_body_schema(get_op).get("properties") or {}) | set(n for _, n in _params(api, get_path, get_op))}
        asked = set(str(q.get("field")) for q in (spec.get("identity") or {}).get("questions") or [] if isinstance(q, dict))
        keys -= asked | {alias(f) for f in asked} | {None}
    reserved = RESERVED | named
    props = schema.get("properties") or {}
    body, headers, moved, required = {}, {"Content-Type": {"type": "string", "default": "application/json"}}, [], []
    # A path or query parameter a call variable of its name fills goes into the URL as {{var}}, resolved like a body
    # default. Any other is a body field the model fills (an engine-run call takes a variable instead), which the
    # pre-hook moves into the URL path, the query or the headers.
    for (where, name), param in _params(api, path, op).items():
        pschema = param.get("schema") if isinstance(param.get("schema"), dict) else {}
        if where == "header" and AUTH_HEADER.search(name):
            continue
        alike = None if name in named else _alike(name, call_vars)
        if (name in named if where == "path" else name in call_vars):
            if where == "path":
                url = url.replace("{" + name + "}", "{{" + name + "}}")
            elif where == "query":
                url += ("&" if "?" in url else "?") + name + "={{" + name + "}}"
            else:
                headers[name] = {"type": "string", "default": "{{" + name + "}}"}
        elif alike:
            # The prepare node copies the variable to the parameter's name (compile_workflow); the pre-hook fills it too.
            if where == "path" and re.fullmatch(r"\w+", name):
                url = url.replace("{" + name + "}", "{{" + name + "}}")
            moved.append([where, name, alike, True])
        elif "const" in pschema or len(pschema.get("enum") or []) == 1 or (where == "header" and "default" in pschema):
            value = pschema["const"] if "const" in pschema else pschema["enum"][0] if len(pschema.get("enum") or []) == 1 else pschema["default"]
            if where == "header":
                headers[name] = {"type": "string", "default": str(value)}
            elif where == "query":
                url += ("&" if "?" in url else "?") + urllib.parse.urlencode([(name, str(value))])
            else:
                moved.append([where, name, None, name in props])
                body.setdefault(name, {"type": pschema.get("type", "string"), "default": value})
        elif model_filled:
            leaf = dict(pschema, description=" ".join(t for t in (param.get("description"), pschema.get("description")) if t))
            body.setdefault(name, _leaf(leaf, "{{" + (f"{tool}_{name}" if name in reserved else name) + "}}", hints.get(name)))
            moved.append([where, name, None, name in props])
            if where == "path" or param.get("required"):
                required.append(name)
        elif where == "path" or param.get("required"):
            source = _engine_source(api, name, call_vars)
            if source is None and where == "path":
                url = url.replace("{" + name + "}", "{{" + name + "}}")
            elif source is not None:
                moved.append([where, name, source, True])
    baked = set()
    for field, prop in props.items():
        prop = prop if isinstance(prop, dict) else {}
        source = alias(field)
        # In the identity check only identifiers are baked; anything else there is the caller's answer.
        identifier = any(n == "id" or n.endswith(("_id", "_ref")) for n in (field, source or "")) or field in keys or source in keys
        if source and (tool != "verify_identity" or identifier):
            # Call identifiers such as customer_id are baked from the call variable of the same name, or of a name like it.
            body[field] = {"type": prop.get("type", "string"), "default": "{{" + source + "}}"}
            baked.add(field)
        elif "const" in prop or len(prop.get("enum") or []) == 1 or (not model_filled and "default" in prop):
            # A fixed value from the API (a const, a one-value enum, or the default of a field no model fills) is sent as it is.
            value = prop["const"] if "const" in prop else prop["enum"][0] if len(prop.get("enum") or []) == 1 else prop["default"]
            body[field] = {"type": prop.get("type", "string"), "default": value}
        elif model_filled:
            # A placeholder with no variable behind it leaves the field to the model (verified pattern).
            name = f"{tool}_{field}" if field in reserved else field
            body[field] = _leaf(prop, "{{" + name + "}}", hints.get(field))
        elif field in (schema.get("required") or []):
            # A code-run tool has no model to fill a required field; take the variable of the same name, or the one the
            # identity check gave.
            body[field] = {"type": prop.get("type", "string"), "default": "{{" + (_engine_source(api, field, call_vars) or field) + "}}"}
    function = {
        "name": tool,
        "handler": "__function__:api_call",
        "description": description or op.get("summary") or tool,
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "default": url},
            "method": {"type": "string", "default": method.upper()},
            "connect_retries": {"type": "number", "default": 0 if max_retries == 0 else 2},
            "headers": {"type": "object", "properties": headers},
            "body": {"type": "object", "properties": body,
                     "required": [f for f in schema.get("required") or [] if f not in call_vars | baked] + [f for f in required if f not in props]},
        }},
    }
    identity = spec.get("identity") or {}
    flag = identity.get("complete_flag") or "all_verified"
    tool_obj = {"type": "function", "config": {"timeoutMs": 12000, "maxRetries": max_retries}, "function": function,
                "post_process_code": _post_hook(tool, flag, identity.get("answer_flag"), identity.get("complete_value"), identity.get("answer_value"),
                                               identity.get("max_wrong_answers"), tool == "verify_identity" and not _per_answer(spec, props))}
    hook = _param_hook(moved) if moved else ""
    if tool == "close_call":
        # The outcome is the request's enum property; the reason is the one free-text field beside it.
        outcome = _enum_prop(props, "outcome") or "outcome"
        free = [f for f, v in props.items() if f != outcome and f not in call_vars | baked and isinstance(v, dict) and v.get("type", "string") == "string"
                and not v.get("enum") and not (f == "id" or f.endswith(("_id", "_ref")))]
        reason = "reason" if "reason" in props else free[0] if len(free) == 1 else None
        # A reason the API requires is kept for every outcome; only an empty value or a placeholder is removed then.
        silent = [] if reason in (schema.get("required") or []) else [o for o in (spec.get("outcomes") or {}).get("no_reason", []) if isinstance(o, str)]
        # The model often sends its last add_note or create_promise in the same turn as close_call, and the
        # platform runs them concurrently: a close that lands first makes them fail. The goodbye is already said.
        hook += (
            "try:\n    import datetime\n    end = datetime.datetime.now() + datetime.timedelta(seconds=1.5)\n"
            "    while datetime.datetime.now() < end:\n        pass\nexcept Exception:\n    pass\n")
        if reason:
            hook += (
                "try:\n    b = config.get('body')\n    if isinstance(b, dict):\n"
                f"        r = str(b.get({reason!r}) or '').strip()\n"
                f"        if b.get({outcome!r}) in {json.dumps(silent)} or not r or r.startswith(chr(123)):\n"
                f"            b.pop({reason!r}, None)\nexcept Exception:\n    pass\n")
    if hook:
        tool_obj["pre_process_code"] = hook
    return tool_obj


def _copy_code(spec, tools):
    """Code for the first node: each call variable a tool URL's {{placeholder}} is named like (musteri_no for musteriNo) is
    copied to the placeholder's name before any tool runs. Empty when no URL needs one."""
    named, call_vars = _call_vars(spec)
    urls = [str(t["function"]["parameters"]["properties"]["url"]["default"]) for t in tools]
    pairs = sorted({(n, _alike(n, call_vars)) for u in urls for n in re.findall(r"\{\{(\w+)\}\}", u) if n not in named and _alike(n, call_vars)})
    if not pairs:
        return ""
    return ("import json\ntry:\n    for _to, _from in json.loads(" + _py_literal(json.dumps(pairs)) + "):\n"
            "        if str(vars.get(_from) or '').strip():\n            vars[_to] = vars[_from]\nexcept Exception:\n    pass\n")


def _true(variable, value=None):
    # The hook compares lowercased; the gate compares strings exactly, so it gets each spelling (and 1 is not True here).
    operands = ["true", "True"]
    if value is not None and value is not True and str(value) not in ("", "true", "True"):
        text = str(value)
        operands += [v for v in dict.fromkeys([text, text.lower(), text.upper(), text.capitalize()]) if v not in operands]
    return [{"variable": variable, "operator": "equals", "operand": o} for o in operands]


def _closed_transition(target="hang_up"):
    return {"target_node": target, "description": "close_call succeeded", "condition": {"logic": "or", "conditions":
            [{"variable": "close_call_success_count", "operator": "greater_than", "operand": 0}]}}


def _model_transition(target, description):
    """A transition the dialogue model takes by calling transition_to_<target> (workflow-format.md, tool-call transitions)."""
    return {"target_node": target, "description": description, "is_tool_call": True,
            "condition": {"operator": "matches_intent", "description": description}}


def _end_transition(have):
    return _closed_transition() if "close_call" in have else _model_transition("hang_up", END_CALL)


def _english(spec):
    return str(spec.get("language") or "English").strip().lower().startswith("en")


# Seen in a Turkish rehearsal: told to say the FRAME's quoted sentences in Turkish, the agent still said "Go on." in English,
# and the opening said a customer record's "Mr" as is. For a language listed here the sentences are written in it, and an
# English honorific in the record is said its way. Other languages keep the instruction to translate.
SPOKEN = {
    "Turkish": {
        "phrases": {"Go on.": "Devam edin lütfen.",
                    "Sorry, I missed that, could you say it again?": "Kusura bakmayın, anlayamadım; tekrar söyler misiniz?",
                    "That is the amount I mentioned.": "Bu, az önce söylediğim tutar.",
                    '"nineteen ninety" is 1990 and "twenty one" is 21': '"bin dokuz yüz doksan" is 1990 and "yirmi bir" is 21'},
        "titles": {"mr": "Bay", "mrs": "Bayan", "ms": "Bayan", "miss": "Bayan"},
    },
}


def _spoken(language):
    return SPOKEN.get(language) or {}


def _title_code(language):
    """Code for the first node: an English honorific in the record ('Mr') becomes the language's word ('Bay') before the
    opening says it. Empty when the language has no list."""
    titles = _spoken(language).get("titles")
    if not titles:
        return ""
    return ("import json\ntry:\n    _said = json.loads(" + _py_literal(json.dumps(titles)) + ").get(str(vars.get('title') or '').strip().strip('.').lower())\n"
            "    if _said:\n        vars['title'] = _said\nexcept Exception:\n    pass\n")


def _first_turn(spec):
    """The agent's first turn. Seen in a held-out Turkish brief: the opening sentence is a statement and the policy asks
    '{ad} {soyad} ile mi görüşüyorum?' right after it; the example calls say both in one turn, but the agent said the
    statement alone and the caller had to answer it first. An opening without a question gets the first quoted question
    of the pre-verification checklist that names the person through call variables."""
    line = spec.get("opening_line") or "Hello."
    if "?" in line:
        return line
    names = set(spec.get("call_variables") or []) - {spec.get("now_variable")}
    steps = str((spec.get("policy") or {}).get("before_verification") or "")
    for m in re.finditer(r"(?<!\w)['\"“‘]([^'\"“”‘’\n]{3,120}\?)['\"”’]", steps):
        question = m.group(1)
        used = re.findall(r"\{\{\s*([^}]+?)\s*\}\}", question)
        if not used:
            # Seen in another read of the same brief: 'Ad soyad ile mi görüşüyorum?', the call variables by their bare names.
            for name in sorted(names, key=lambda n: -len(str(n))):
                question = re.sub(r"(?<![\w{])" + re.escape(str(name)).replace("_", "[ _]") + r"(?![\w}])", "{{" + str(name) + "}}",
                                  question, flags=re.I)
            used = re.findall(r"\{\{\s*([^}]+?)\s*\}\}", question)
        if used and set(used) <= names:
            return line.rstrip() + " " + question.strip()
    return line


def compile_workflow(spec, api, briefs):
    from .spec import normalize_spec, resolve_refs, who_variables
    api = resolve_refs(api)
    spec = normalize_spec(spec, api)
    policy = spec.get("policy") or {}
    identity = spec.get("identity") or {}
    flag = identity.get("complete_flag") or "all_verified"
    raw = "\n\n".join(f"--- {d['path']} ---\n{d['text']}" for d in briefs)
    # A role the bank has no operation for has no tool, and no sentence tells the agent to use one.
    have = {t for t in TOOL_NAMES if _find(api, t)[0] is not None}
    language = str(spec.get("language") or "English")
    frame, go_on = FRAME, "Go on."
    if not _english(spec):
        for said, own in _spoken(language).get("phrases", {}).items():
            frame = frame.replace(said, own)
        go_on = _spoken(language).get("phrases", {}).get(go_on, go_on)
    system_prompt = "\n\n".join(filter(None, [
        frame,
        "Language: " + language + "." + ("" if _english(spec) else
            f" Say everything in {language}. The quoted example sentences above (such as \"{go_on}\") show only what to say: say"
            f" them in {language}. Say dates in words as a {language} speaker does (day, month and weekday), and numbers the"
            f" customer says in {language} words, such as a year, are complete as said."),
        "BANK POLICY (verbatim documents, in the order given):\n" + raw,
        ("PRECEDENCE AND CLARIFICATIONS:\n" + policy["precedence"]) if policy.get("precedence") else "",
        CLOSE_RULE if "close_call" in have else CLOSE_RULE_NO_TOOL,
        "\n".join(line for tool, line in NO_TOOL.items() if tool not in have),
        ("CLOSING TABLE:\n" + policy["closing"]) if policy.get("closing") else "",
    ]))
    facts_code = ("SPEC_JSON = " + _py_literal(json.dumps(code_spec(spec), ensure_ascii=True, separators=(",", ":"))) + "\n"
                  + compact_code((SNIPPETS / "facts.py").read_text()))

    def code_node(name, target, before=(), code=None):
        return {"name": name, "node_type": "code", "passthrough": True, "passthrough_default_transition": target,
                "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True,
                "pre_actions": [{"type": "function", "function": {"name": "code_exec", "handler": "__function__:code_exec",
                                 "parameters": {"type": "object", "properties": {"code": {"type": "string", "default": code or facts_code},
                                                                                 "timeout_ms": {"type": "number", "default": 10000}}}}}],
                "transitions": list(before) + [{"target_node": target, "description": "always", "condition": {"operator": "always"}}]}

    asked = (_body_schema(operation(api, "verify_identity")[1]).get("properties") or {}) if "verify_identity" in have else {}
    per_answer = "verify_identity" in have and _per_answer(spec, asked)
    # All the answers at once: each question is listed under the request's own field for it (dogumTarihi for dogum_tarihi).
    questions = "\n".join(f"- {(not per_answer and _alike(q.get('field'), asked)) or q.get('field')}: {q.get('ask')} (send as: {q.get('answer_format')})"
                          for q in identity.get("questions", []))
    # Seen live: with no value of its own in the prompt, the agent asked every customer for the brief's example name.
    # Only who the call is for: an amount or a security answer passed as a call variable must not be in reach before
    # identity is verified.
    this_call = who_variables(spec)
    # Without an account read the agent goes from identity straight to the facts code; without an identity check the
    # model itself says when the policy's identity check is done.
    verified = "load_account" if "get_account" in have else "account_facts"
    if "verify_identity" not in have:
        # The model is the check: the call's own record of an answer (a call variable named like the question's field) is its key.
        record = [(q.get("field"), _alike(q.get("field"), _call_vars(spec)[0] - {spec.get("now_variable")}))
                  for q in identity.get("questions") or [] if isinstance(q, dict)]
        check = "\n\n".join(filter(None, [
            ("THE BANK'S RECORD of the answers (compare each answer with it as the policy says; never say, read out or hint these"
             " values):\n" + "\n".join(f"- {f}: {{{{{v}}}}}" for f, v in record if v)) if any(v for _, v in record) else "",
            f"This bank has no identity-check tool. Ask the identity questions the policy gives, one at a time, and judge the"
            f" answers as the policy says. Once the policy's identity check is passed, call transition_to_{verified} in the"
            " same message as your next words; never call it before."]))
    elif per_answer:
        check = ("Call verify_identity once for each answer the customer gives, with the field of the question you asked. An answer that"
                 " comes together with a question or a complaint (a date followed by \"so how much do I owe?\") is still an answer: verify it"
                 " first, then reply.")
    else:
        check = ("Ask every security question first, one at a time, then call verify_identity once with all the answers, each in its"
                 " own field. An answer that comes together with a question or a complaint (a date followed by \"so how much do I"
                 " owe?\") is still an answer: keep it and go on.")
    identify_task = "\n\n".join(filter(None, [
        "PHASE: before identity verification. The account is not visible yet and must not be discussed.",
        ("THIS CALL (who this call is for; names in the policy documents are only examples):\n"
         + "\n".join(f"- {v}: {{{{{v}}}}}" for v in this_call)) if this_call else "",
        policy.get("before_verification"),
        ("Security questions, in order (verify_identity field value: question):\n" if per_answer else
         "Security questions, in order (verify_identity field: question):\n" if "verify_identity" in have else
         "Security questions, in order:\n") + questions if questions else "",
        check,
        "DATE FACTS:\n{{date_facts}}",
    ]))
    # Without an account read the call's own values are all the agent has; identity is verified by now.
    values = [v for v in spec.get("call_variables") or [] if v != spec.get("now_variable")]
    negotiate_task = "\n\n".join(filter(None, [
        "PHASE: identity is verified. The get_account result is in ACCOUNT FACTS." if "get_account" in have else
        "PHASE: identity is verified. This bank has no account lookup: the account is what THIS CALL and the policy say.",
        ("THIS CALL:\n" + "\n".join(f"- {v}: {{{{{v}}}}}" for v in values)) if "get_account" not in have and values else "",
        BRIEF_THINKING if NEGOTIATE_REASONING == "enabled" else "",
        policy.get("after_verification"),
        "ACCOUNT FACTS:\n{{account_facts}}" if "get_account" in have else "",
        "PROPOSAL COUNT:\n{{plan_state}}" if COUNT_CHECK else "",
        "NAMED DAY CHECK:\n{{named_day_facts}}" if DATE_CHECK else "",
        "DATE FACTS:\n{{date_facts}}",
        # Last, so the next step is the most recent text the model reads: seen in chat runs, a NEXT STEP in the middle of the
        # prompt was skipped for a read-back or one more offer.
        "NEXT STEP (from the PROPOSAL COUNT; the policy's own exceptions, such as hardship, come first):\n{{next_step}}" if COUNT_CHECK else "",
    ]))
    # Once no product has a proposal left, the persuasion plans are out of sight: seen live, the model kept offering floors.
    promise = "create_promise" in have
    wrap_up_task = "\n\n".join(filter(None, [
        "PHASE: the payment proposals are finished. For a product marked DONE propose no amount and no date. Finish the call in"
        " this order: read back what the customer offered and ask them to confirm it as the policy says; after a clear yes"
        + (" call create_promise for that product;" if promise else " the promise is agreed;")
        + " for each product without a promise do what the policy prescribes for it"
        + (" (when the policy asks for a note, call add_note once for that product with the reason the policy gives)" if "add_note" in have else "")
        + ", except a product whose line below says it is already done;"
        " say what the policy requires after a " + ("recorded " if promise else "") + "promise; then say the closing words and "
        + ("call close_call." if "close_call" in have else "end the call."),
        "NAMED DAY CHECK:\n{{named_day_facts}}",
        "DATE FACTS:\n{{date_facts}}",
        # Last, so the next step is the most recent text the model reads.
        "PRODUCTS AND NEXT STEP:\n{{wrap_up_facts}}",
    ]))
    descriptions = spec.get("tool_descriptions") or {}
    pre_tools = [t for t in ("verify_identity", "schedule_callback", "transfer_to_agent", "close_call") if t in have]
    post_tools = [t for t in ("create_promise", "add_note", "schedule_callback", "transfer_to_agent", "close_call") if t in have]
    # The contract's other operations (an SMS, a payment link, a statement copy) are tools of the negotiation.
    extras = [api_tool(api, name, spec, descriptions.get(name, ""), key=key) for name, key in extra_tools(api).items()]
    get_account = None
    if "get_account" in have:
        # One retry: "if it fails, try once more" is the usual rule, and a third call would show in the bank's record.
        get_account = api_tool(api, "get_account", spec, model_filled=False, max_retries=1)
        get_account.pop("post_process_code")
    # An empty list_field: the account read returns the one product (a statement) or the array itself.
    list_field = (spec.get("account") or {}).get("list_field")
    list_field = "products" if list_field is None else str(list_field).strip(".")

    negotiate_node = {
        "name": "negotiate", "node_type": "conversation",
        "on_enter": {"type": "llm"}, "on_enter_first_entry_only": True,
        "task_message": negotiate_task,
        "tools": [api_tool(api, t, spec, descriptions.get(t, "")) for t in post_tools] + extras,
        "max_node_turns": 120, "max_turn_transition": "hang_up",
        # A date-typed extraction resolves "tomorrow" against the server clock, not the call's date (seen live),
        # so the customer's own words are copied and resolved in code from the call's date.
        # The free-text fields take low-confidence values: in 105 chat calls, all 14 values the platform dropped for
        # confidence 0.44-0.59 were right ("Monday the 26th" at 0.49), and a dropped day or refusal skipped the code check.
        **({"extraction_schema": [{
            "name": "named_day_words", "type": "string", "min_confidence": LOOSE,
            "description": "The customer's own words for the one exact day they name in their LAST message as a day to pay or as a day"
                           " they ask about, copied as said, for example 'Monday the 26th', 'the thirtieth', '26 October', 'next Friday',"
                           " 'tomorrow'. Empty when the last message names no exact day or only a vague period such as 'next week',"
                           " 'the week after next', 'end of the month' or 'when my salary comes'. Not a day the customer only says"
                           " they cannot pay on, such as 'today' in 'I can't pay today'."}] + ([{
            # Attempt counting across products is the step the phone model gets wrong most; code keeps the count.
            "name": "refused_products", "type": "string", "min_confidence": LOOSE,
            "description": "The products the customer flatly refuses to pay in their LAST message, as an answer to a question asking"
                           " them to pay. Name each refused product with the assistant's own words for it, for example 'personal loan',"
                           " 'credit card', 'car loan and personal loan'. When the customer only says no, name the product or products"
                           " the assistant's last question asked about, and write 'all' for a plain no to paying all of them."
                           " Never write 'the others' or 'the rest': name those products. A product the customer gives a date or an"
                           " amount for is not refused. 'none' when the last message refuses nothing: it accepts, proposes or asks about"
                           " a date or an amount, only says the amount is too much, mentions illness, a death, job loss or other hardship,"
                           " says it is already paid or disputes it, asks a question, only chats, or is cut off."}, {
            # Only proposals the assistant made are counted: a repeated "none of them" must not use up the others' steps.
            "name": "proposed_products", "type": "string", "min_confidence": LOOSE,
            "description": "The products that the assistant's most recent payment question asked the customer to pay, named with the"
                           " assistant's own words for them, for example 'credit card' or 'personal loan and car loan'; 'all' when it asked"
                           " about paying all the products together. Skip later assistant messages that ask for no payment, such as a"
                           " reason, 'Go on.' or a request to say it again. 'none' when no payment has been asked yet."}, {
            # A refusal of the agent's answer to the customer's own day or amount is that product's answer to the first ask.
            "name": "dated_products", "type": "string", "min_confidence": LOOSE,
            "description": "The products the customer says they can or will pay on a day, a date or with an amount they give in their LAST"
                           " message, named with the assistant's own words for them, for example 'credit card'; 'all' when the day or"
                           " amount is for all of them. 'none' when the last message names no day, date or amount to pay, or only"
                           " mentions or asks about a product, or says they cannot pay it."}, {
            # Seen in a review: a product that accepted a persuasion proposal stayed in the plan and was proposed again.
            "name": "accepted_products", "type": "string", "min_confidence": 0.6,
            "description": "The products whose payment proposal the customer accepts in their LAST message: a yes to the amount and"
                           " the day the assistant just proposed for them, named with the assistant's own words, for example 'credit"
                           " card'; 'all' when they accept a proposal made for all of them. 'none' when the last message accepts no"
                           " proposal: it refuses, asks a question, gives a day or an amount of their own, only confirms a read-back,"
                           " only says they understand, or only chats."}, {
            # The closing read-back is a fixed line with the amount owed; an amount of the customer's own turns it off.
            "name": "named_amount_words", "type": "string", "min_confidence": LOOSE,
            "description": "An amount of money the customer themselves says they can or will pay in their LAST message, copied as said,"
                           " for example '300', 'two hundred', 'half of it'. 'none' when the last message names no amount of their own:"
                           " it only accepts, refuses or repeats the assistant's amount, or names only a day."}, {
            # Seen in a chat run: "why do you need all of them today?" right after the first ask, and the model asked it again.
            "name": "asked_back", "type": "string", "enum_values": ["yes", "no"], "min_confidence": 0.6,
            "description": "'yes' only when the customer's LAST message is just a question about the payment the assistant asked for,"
                           " for example 'why do you need that?', 'why today?', 'why all of them?' or 'which account is this about?',"
                           " with no answer in it: it refuses nothing, names no day or amount and accepts nothing. 'no' for everything"
                           " else, including a request (another plan, lower instalments, a discount, a person, a callback), a question"
                           " about support, a mention of hardship, a dispute or a payment already made, and a message that is cut off."}, {
            # On a plain refusal the next proposal of the plan is a fixed line; anything else in the answer is left to the model.
            "name": "plain_refusal", "type": "string", "enum_values": ["yes", "no"], "min_confidence": 0.6,
            "description": "'yes' only when the customer's LAST message just declines the payment the assistant proposed or asked for"
                           " ('no', 'I can't', 'not that either', 'no, whatever you offer'), with nothing else in it. 'no' when it also"
                           " or instead asks a question, gives a reason such as illness, a death, job loss or other hardship, disputes the"
                           " debt, says it is already paid, says the amount is too much, asks for something (another plan, lower"
                           " instalments, a discount, a person, a callback), names a day or an amount, accepts, declines something that is"
                           " not a payment (an offer of support, a transfer, a callback), says they do not want to talk or asks to end the"
                           " call or to stop calling, or is cut off."}, {
            # The fixed line never repeats the amount the customer has just refused (a floor offered after 'too much').
            "name": "proposed_amount", "type": "string", "min_confidence": LOOSE,
            "description": "The amount of money the assistant's LAST message proposed or asked the customer to pay, in digits as the"
                           " assistant said it, for example '213' or '61.20'. 'none' when that message proposed no amount."}] if COUNT_CHECK else [])}
           if DATE_CHECK else {}),
        # Multi-rule date, amount and per-product attempt decisions happen here.
        "reasoning_override": NEGOTIATE_REASONING,
        "transitions": [_end_transition(have)] + ([{
            "target_node": "check_date", "description": "the customer named a day or refused a product",
            "condition": {"logic": "or", "conditions": [{"logic": "and", "conditions": [
                {"variable": v, "operator": "is_set"},
                {"variable": v, "operator": "not_equals", "operand": ""},
                {"variable": v, "operator": "not_equals", "operand": "none"}] + extra}
                for v, extra in [("named_day_words", [])] + ([("refused_products", [
                    # One product keeps the flow that passes today.
                    {"variable": "product_count", "operator": "not_equals", "operand": "1"}]), ("named_amount_words", [
                    {"variable": "product_count", "operator": "not_equals", "operand": "1"}]), ("accepted_products", [
                    {"variable": "product_count", "operator": "not_equals", "operand": "1"}])] if COUNT_CHECK else [])] + ([{
                # A question back while the first ask is open: the plan names attempt 1 instead of the first ask again.
                "logic": "and", "conditions": [
                    {"variable": "asked_back", "operator": "equals", "operand": "yes"},
                    {"variable": "first_ask_open", "operator": "equals", "operand": "yes"},
                    {"variable": "product_count", "operator": "not_equals", "operand": "1"}]}] if COUNT_CHECK else [])}}] if DATE_CHECK else []),
    }

    identify_tools = [api_tool(api, t, spec, descriptions.get(t, "")) for t in pre_tools]
    copy = _copy_code(spec, identify_tools + negotiate_node["tools"] + ([get_account] if get_account else []))
    title = "" if _english(spec) else _title_code(language)
    nodes = {
        "prepare": code_node("prepare", "identify", code=(title + copy + facts_code) if (title or copy) else None),
        "identify": {
            "name": "identify", "node_type": "conversation",
            "on_enter": {"type": "tts", "text": _first_turn(spec)}, "on_enter_first_entry_only": True,
            "task_message": identify_task,
            "tools": identify_tools,
            "max_node_turns": 80, "max_turn_transition": "hang_up",
            "transitions": [
                {"target_node": verified, "description": "identity fully verified", "condition": {"logic": "or", "conditions": _true(f"verify_identity_response.data.{flag}", (spec.get("identity") or {}).get("complete_value"))}}
                if "verify_identity" in have else _model_transition(verified, "The identity check the policy requires is passed."),
                _end_transition(have),
            ],
        },
        **({"load_account": {
            "name": "load_account", "node_type": "api_request", "passthrough": True, "passthrough_default_transition": "account_facts",
            "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True, "suppress_tool_results": False,
            "pre_actions": [get_account],
            "response_mapping": [{"path": f"data.{list_field}" if list_field else "data", "variable": "account_products"}],
            "transitions": [{"target_node": "account_facts", "description": "always", "condition": {"operator": "always"}}],
        }} if get_account else {}),
        "account_facts": code_node("account_facts", "negotiate"),
        "negotiate": negotiate_node,
        **({"check_date": code_node("check_date", "negotiate", [] if not COUNT_CHECK else [{
            # Seen live: on the turn of the last refusal the model made one more proposal, copying its earlier ones. When the
            # code can build the read-back, that turn's reply is a fixed line (no model call); later turns use wrap_up.
            "target_node": "wrap_up_readback", "description": "no product has a proposal left and the read-back is a fixed line",
            "condition": {"logic": "or", "conditions": [{"logic": "and", "conditions": [
                {"variable": "negotiation_done", "operator": "equals", "operand": "yes"},
                {"variable": "wrap_up_mode", "operator": "equals", "operand": "say"}]}]}}, {
            # Seen live (4 calls): after the fixed read-back, "Yes, I confirm" went to wrap_up's first entry, whose entry line
            # cannot call a tool, and create_promise came out as text. Back in the node already entered, it is a turn with tools.
            "target_node": "wrap_up_readback", "description": "no product has a proposal left and the fixed read-back was already said",
            "condition": {"logic": "or", "conditions": [{"logic": "and", "conditions": [
                {"variable": "negotiation_done", "operator": "equals", "operand": "yes"},
                {"variable": "readback_said", "operator": "not_equals", "operand": "{}"}]}]}}, {
            "target_node": "wrap_up", "description": "no product has a proposal left",
            "condition": {"logic": "or", "conditions": [{"variable": "negotiation_done", "operator": "equals", "operand": "yes"}]}}, {
            # Seen in a chat run: the model said its own previous amount instead of the step's. A plain refusal's next
            # proposal is a fixed line, said on every entry.
            "target_node": "say_proposal", "description": "the next proposal is a fixed line",
            "condition": {"logic": "or", "conditions": [{"variable": "proposal_mode", "operator": "equals", "operand": "say"}]}}])}
           if DATE_CHECK else {}),
        **({"wrap_up": dict(negotiate_node, name="wrap_up", task_message=wrap_up_task,
                            # The entry line is the reply on the turn of the last refusal: it is given the one thing to say.
                            on_enter={"type": "llm", "prompt": "Reply to the customer now, doing exactly the NEXT STEP at the end of your task: {{wrap_up_step}}"}),
            "wrap_up_readback": dict(negotiate_node, name="wrap_up_readback", task_message=wrap_up_task,
                                     on_enter={"type": "tts", "text": "{{wrap_up_say}}"}),
            "say_proposal": dict(negotiate_node, name="say_proposal", on_enter={"type": "tts", "text": "{{proposal_say}}"},
                                 on_enter_first_entry_only=False)}
           if DATE_CHECK and COUNT_CHECK else {}),
        "hang_up": {
            "name": "hang_up", "node_type": "end_call", "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True,
            "transitions": [],
            "terminal": {"type": "function", "function": {"name": "call_closed", "handler": "__function__:end_call",
                         "parameters": {"type": "object", "properties": {"message_mode": {"type": "string", "default": "none"}}}}},
        },
    }
    return {"initial_node": "prepare", "system_prompt": system_prompt, "global_nodes": {}, "nodes": nodes,
            "test_variables": spec.get("test_variables") or {}}
