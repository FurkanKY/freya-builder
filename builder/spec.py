"""Shape fixes that make the compiler independent of small variations in the model's JSON and the bank's OpenAPI.

Nothing here knows a bank: it only coerces types, resolves local $refs and maps names to the forms the
compiler and the sandbox code expect.
"""
import copy
import re

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def resolve_refs(api):
    """Return a copy of the OpenAPI document with local '#/...' references inlined (cycles left as-is)."""
    root = api

    def lookup(ref):
        node = root
        for part in ref.lstrip("#/").split("/"):
            node = node[part.replace("~1", "/").replace("~0", "~")]
        return node

    def walk(node, seen):
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/") and ref not in seen:
                try:
                    target = lookup(ref)
                except (KeyError, TypeError):
                    return {k: walk(v, seen) for k, v in node.items()}
                merged = dict(walk(copy.deepcopy(target), seen | {ref}))
                merged.update({k: walk(v, seen) for k, v in node.items() if k != "$ref"})
                return merged
            return {k: walk(v, seen) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v, seen) for v in node]
        return node

    return walk(api, frozenset())


def _text(value):
    """Policy text may come back as a list of steps or a mapping; the compiler needs one string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_text(v) for v in value)
    if isinstance(value, dict):
        return "\n".join(f"{k}: {_text(v)}" for k, v in value.items())
    return str(value)


def _names(value, key="name"):
    if isinstance(value, str):
        return [v.strip() for v in re.split(r"[,;]", value) if v.strip()]
    if isinstance(value, list):
        return [str(v.get(key) if isinstance(v, dict) else v) for v in value if v not in (None, "")]
    if isinstance(value, dict):
        return [str(k) for k in value]
    return []


def weekdays(value):
    """Map 'mon', 'Monday', 'Monday to Friday' or ['Mon', ...] to canonical weekday names."""
    items = value if isinstance(value, list) else [value]
    out = []
    for item in items:
        text = str(item or "").strip().lower()
        found = [d for d in WEEKDAYS if re.search(r"\b" + d[:3].lower() + r"[a-z]*\b", text)]
        if len(found) == 2 and re.search(r"\b(to|through|until|till|-|–)\b|[-–]", text):
            a, b = WEEKDAYS.index(found[0]), WEEKDAYS.index(found[1])
            found = WEEKDAYS[a:b + 1] if a <= b else WEEKDAYS[a:] + WEEKDAYS[:b + 1]
        out += [d for d in found if d not in out]
    return [d for d in WEEKDAYS if d in out]


def _by_type(value, types):
    """A per-type mapping given as one string applies to every product type."""
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}
    if (isinstance(value, str) and value) or (isinstance(value, (int, float)) and not isinstance(value, bool)):
        return {t: value for t in types} or {"*": value}
    return {}


def _product_types(api, list_field, type_field):
    try:
        from .compile import operation
        _, op = operation(api, "get_account")
        props = op.get("responses", {}).get("200", {}).get("content", {}).get("application/json", {}).get("schema", {}).get("properties", {})
        items = {}
        for part in str(list_field or "").split("."):
            items = props.get(part, {})
            props = items.get("properties", {})
        return [str(t) for t in items.get("items", {}).get("properties", {}).get(type_field, {}).get("enum", [])]
    except Exception:
        return []


def _call_templates(text, call_vars):
    """{first_name} or <first_name> for a call variable becomes the platform's {{first_name}}; anything else is left as it is."""
    return re.sub(r"(?<!\{)\{\s*(\w+)\s*\}(?!\})|<\s*(\w+)\s*>",
                  lambda m: "{{" + (m.group(1) or m.group(2)) + "}}" if (m.group(1) or m.group(2)) in call_vars else m.group(0), text)


def normalize_spec(spec, api):
    """Coerce a model-written spec into the types the compiler and facts code expect. Idempotent."""
    spec = copy.deepcopy(spec) if isinstance(spec, dict) else {}
    spec["call_variables"] = _names(spec.get("call_variables"))
    for key in ("language", "now_variable", "opening_line"):
        if spec.get(key) is not None and not isinstance(spec[key], str):
            spec[key] = _text(spec[key])
    now = spec.get("now_variable")
    if isinstance(now, str) and now and now not in spec["call_variables"] and \
            not any(re.search(r"now|date|time|today|clock", v, re.I) for v in spec["call_variables"]):
        # Raw material often says only "today"; the clock variable then has to be added, not guessed twice.
        spec["call_variables"].append(now)
    call_vars = set(spec["call_variables"])
    if spec.get("opening_line"):
        # A brief's single-brace {first_name} would otherwise be spoken literally.
        spec["opening_line"] = _call_templates(spec["opening_line"], call_vars)
    identity = spec.get("identity") if isinstance(spec.get("identity"), dict) else {}
    questions = []
    for q in identity.get("questions") or []:
        if isinstance(q, dict):
            questions.append({k: _text(v) for k, v in q.items()})
        elif q not in (None, ""):
            questions.append({"field": str(q), "ask": "", "answer_format": ""})
    identity["questions"] = questions
    spec["identity"] = identity
    calendar = spec.get("calendar") if isinstance(spec.get("calendar"), dict) else {}
    days = weekdays(calendar.get("business_weekdays"))
    calendar["business_weekdays"] = days or WEEKDAYS[:5]
    holidays = []
    for h in calendar.get("holidays") or []:
        if isinstance(h, dict):
            holidays.append({"date": str(h.get("date", ""))[:10], "name": str(h.get("name") or "bank holiday")})
        elif isinstance(h, str):
            m = re.search(r"\d{4}-\d{2}-\d{2}", h)
            holidays.append({"date": m.group(0) if m else h, "name": h.replace(m.group(0), "").strip(" :-–()") or "bank holiday" if m else "bank holiday"})
    calendar["holidays"] = holidays
    rule = str(calendar.get("closed_day_rule") or "").lower()
    calendar["closed_day_rule"] = ("previous_business_day" if re.search(r"previous|prior|before|earlier", rule) else
                                   "next_business_day" if re.search(r"next|following|after|later", rule) else
                                   "ask_again" if re.search(r"ask|another|other|again", rule) else "none")
    spec["calendar"] = calendar
    account = spec.get("account") if isinstance(spec.get("account"), dict) else {}
    types = _product_types(api, account.get("list_field"), account.get("type_field"))
    for key in ("floor_field_by_type", "spoken_name_by_type"):
        account[key] = _by_type(account.get(key), types)
    bands = []
    for band in account.get("bands") or []:
        if not isinstance(band, dict):
            continue
        band = dict(band)
        for bound in ("min", "max"):
            try:
                band[bound] = float(band[bound]) if band.get(bound) not in (None, "") else (0 if bound == "min" else 1e9)
                band[bound] = int(band[bound]) if band[bound] == int(band[bound]) else band[bound]
            except (TypeError, ValueError):
                pass
        if not isinstance(band.get("deadline"), dict):
            band["deadline"] = {"type": "none", "count": 0, "date": ""}
        kind = str(band["deadline"].get("type") or "").lower()
        # Only this month's end maps to the month-end kinds; 'end of next month' or 'months after today' stay unknown ('see policy').
        words = set(re.split(r"[^a-z0-9]+", kind))
        if "month" in words and words & {"end", "last", "final"} and not words & {"next", "after", "following"} and not re.search(r"\d", kind):
            band["deadline"]["type"] = "last_business_day_of_month" if re.search(r"business|working|work_day|workday", kind) else "end_of_month"
        plan = band.get("attempt_plan")
        band["attempt_plan"] = [_text(p) for p in plan] if isinstance(plan, list) else ([plan] if isinstance(plan, str) and plan else [])
        bands.append(band)
    account["bands"] = bands
    spec["account"] = account
    outcomes = spec.get("outcomes")
    if isinstance(outcomes, list):
        outcomes = {"no_reason": outcomes}
    outcomes = outcomes if isinstance(outcomes, dict) else {}
    outcomes["no_reason"] = _names(outcomes.get("no_reason"))
    spec["outcomes"] = outcomes
    for section in ("tool_descriptions", "tool_field_hints"):
        value = spec.get(section)
        value = value if isinstance(value, dict) else {}
        fixed = {}
        for key, item in value.items():
            name = str(key).strip().strip("/").split("/")[-1]
            if section == "tool_descriptions":
                fixed[name] = _text(item)
            else:
                fixed[name] = {str(f): _text(h) for f, h in item.items()} if isinstance(item, dict) else {}
        spec[section] = fixed
    policy = spec.get("policy") if isinstance(spec.get("policy"), dict) else {"after_verification": _text(spec.get("policy"))}
    # Seen live: a read wrote "Ask 'Am I speaking with {title} {last_name}?'", the platform filled nothing in and the agent
    # asked every customer for the example name in the brief.
    spec["policy"] = {k: _call_templates(_text(v), call_vars) for k, v in policy.items()}
    return spec
