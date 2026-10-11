"""Shape fixes that make the compiler independent of small variations in the model's JSON and the bank's OpenAPI.

Nothing here knows a bank: it only coerces types, resolves local $refs and maps names to the forms the
compiler and the sandbox code expect.
"""
import copy
import re

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
# Turkish is matched on folded text: lowercase, the dotted and dotless i as 'i', Turkish letters as ASCII.
FOLD = str.maketrans("\u00e7\u011f\u0131\u00f6\u015f\u00fc\u00e2\u00ee\u00fb", "cgiosuaiu", "\u0307")
TR_DAYS = dict(zip("pazartesi sali carsamba persembe cuma cumartesi pazar".split(), WEEKDAYS))
TR_DAY_ABBR = dict(zip("pzt sal car per cum cmt paz".split(), WEEKDAYS))
# The endings a Turkish day name takes: plural, then a case ('cumartesileri', 'pazartesiden', 'cumaya').
TR_DAY_END = re.compile(r"(?:l[ae]ri?)?(?:n?[dt][ae]n?|y?[ae]|n?in|si|ki)?")
TR_NUMBERS = {"bir": "1", "iki": "2", "uc": "3", "dort": "4", "bes": "5"}
LANGUAGES = {"Turkish": r"turk(?:ish|ce)?(?: dili)?|tr(?:[-_ ]tr)?", "English": r"english|ingilizce|en(?:[-_ ][a-z]{2})?"}


def fold(text):
    """Text as Turkish words are matched: 'İADE', 'iade' and 'ıade' all give 'iade'; English is only lowercased."""
    return str(text or "").lower().translate(FOLD)


def language_name(value):
    """The language the agent speaks as one name ('tr-TR', 'Türkçe' and 'Turkish' are Turkish); '' when value names none."""
    text = re.sub(r"\s+", " ", _text(value)).strip(" .;:")
    # A known language before a qualifier counts as named: 'Türkçe (resmi dil)', 'Turkish, English on request'.
    head = re.split(r"\s*[(,;/]|\s+-\s+", fold(text))[0].strip()
    for name, pattern in LANGUAGES.items():
        if re.fullmatch(pattern, fold(text)) or re.fullmatch(pattern, head):
            return name
    if not text or len(text.split()) > 4 or re.search(r"[\d<>{}\[\]_]|\b(?:language|speaks?|agent|customer|caller|same|unknown|none|dil|dili)\b", fold(text)):
        return ""
    return text


def success_schema(op):
    """The JSON schema of an operation's success response: 200, else the first 2xx; JSON, else the first content type."""
    responses = op.get("responses") or {}
    key = "200" if "200" in responses else next((k for k in responses if str(k).startswith("2")), None)
    content = (responses.get(key) or {}).get("content") or {}
    media = content.get("application/json") or next((v for v in content.values() if isinstance(v, dict) and v.get("schema")), {})
    return media.get("schema") or {}


def product_schema(op, list_field):
    """The schema of one product in an operation's success response: the items of the array list_field names (a dotted path)
    or the object it names; with no list_field the response itself (one product as an object, or a top-level array).
    None when list_field names nothing in the response."""
    node = success_schema(op)
    for part in str(list_field).split(".") if list_field else []:
        props = node.get("properties") if isinstance(node, dict) else None
        node = props.get(part) if isinstance(props, dict) else None
        if not node or not isinstance(node, dict):
            return None
    items = node.get("items")
    return items if isinstance(items, dict) and items.get("properties") else node


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

    return _merge_all_of(walk(api, frozenset()))


def _merge_all_of(node):
    """An object schema written as allOf of object parts becomes one schema with all their properties and required fields."""
    if isinstance(node, list):
        return [_merge_all_of(v) for v in node]
    if not isinstance(node, dict):
        return node
    node = {k: _merge_all_of(v) for k, v in node.items()}
    parts = node.get("allOf")
    if isinstance(parts, list) and parts and all(isinstance(p, dict) for p in parts):
        merged = {k: v for k, v in node.items() if k != "allOf"}
        props, required = dict(merged.get("properties") or {}), list(merged.get("required") or [])
        for part in parts:
            props.update(part.get("properties") or {})
            required += [r for r in part.get("required") or [] if r not in required]
            for k, v in part.items():
                if k not in ("properties", "required"):
                    merged.setdefault(k, v)
        merged["properties"], merged["required"] = props, required
        merged.setdefault("type", "object")
        return merged
    return node


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


def _tr_days(text):
    """The weekdays a folded Turkish text names, in order ('pazartesiden cumaya' Monday, Friday), and whether the first is a
    'from' ('-den')."""
    words = re.findall(r"[a-z]+", re.sub(r"['\u2019]", "", text))
    # Abbreviations ('Pzt-Cum') only in a text of day words alone: 'per week' is no Thursday.
    abbr = TR_DAY_ABBR if all(w in TR_DAYS or w in TR_DAY_ABBR or w in ("ve", "ila", "kadar", "arasi") for w in words) else {}
    found, start = [], False
    for word in words:
        stem = max((d for d in TR_DAYS if word.startswith(d)), key=len, default=None)
        if stem and TR_DAY_END.fullmatch(word[len(stem):]):
            start = start or (not found and bool(re.fullmatch(r"n?[dt][ae]n", word[len(stem):])))
            found.append(TR_DAYS[stem])
        elif word in abbr:
            found.append(abbr[word])
    return found, start


def weekdays(value):
    """Map 'mon', 'Monday', 'Monday to Friday', 'Pazartesi-Cuma' or ['Mon', ...] to canonical weekday names."""
    items = value if isinstance(value, list) else [value]
    out = []
    for item in items:
        text = str(item or "").strip().lower()
        found = [d for d in WEEKDAYS if re.search(r"\b" + d[:3].lower() + r"[a-z]*\b", text)]
        ranged = re.search(r"\b(to|through|until|till|-|–)\b|[-–]", text)
        if not found:
            found, start = _tr_days(fold(text))
            ranged = ranged or start or re.search(r"\b(?:ila|kadar|arasi\w*)\b", fold(text))
            found += WEEKDAYS[:5] if re.search(r"\bhafta ?ici", fold(text)) else []
        if len(found) == 2 and ranged:
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
        node, props = {}, (product_schema(op, list_field) or {}).get("properties") or {}
        for part in str(type_field or "").split("."):
            node = props.get(part, {}) if isinstance(props, dict) else {}
            props = node.get("properties", {})
        return [str(t) for t in node.get("enum", [])]
    except Exception:
        return []


# A name in brackets; it may start with any letter ('{İsim}', '<Müşteri Adı>').
PLACEHOLDER = re.compile(r"(?<!\{)\{\s*([^\W\d_][\w ]*?)\s*\}(?!\})|<\s*([^\W\d_][\w ]*?)\s*>|\[\s*([^\W\d_][\w ]*?)\s*\]")


def _call_templates(text, call_vars):
    """{first_name}, <First Name> or [first_name] for a call variable becomes the platform's {{first_name}}; anything else
    is left as it is."""
    by_key = {fold(v): v for v in call_vars}

    def one(m):
        name = by_key.get(fold(re.sub(r"\s+", "_", (m.group(1) or m.group(2) or m.group(3)).strip())))
        return "{{" + name + "}}" if name else m.group(0)
    return PLACEHOLDER.sub(one, text)


# Who the call is for, whatever the brief calls it (first/last, given/family, customer, gender). Everything else a call
# variable can hold (an amount, a security answer, an id, the clock, the assistant's own name) stays out of reach until
# the identity is verified.
WHO = re.compile(r"name|title|salutation|honorific|surname|forename|given|family|gender|pronoun|holder", re.I)
NOT_WHO = re.compile(r"agent|bot|assistant|bank|product|campaign|company|operator|brand", re.I)
CALL_DATA = re.compile(r"amount|balance|due|owed|arrear|overdue|debt|past|late|limit|minimum|instal|account|loan|card|payment|band|"
                       r"segment|risk|score|birth|dob|phone|mobile|postcode|post_code|zip|iban|ssn|pin|password|secret|answer|"
                       r"address|email|date|time|today|day|ref|number|^id$|_id$", re.I)
# The same in Turkish, on the folded name ('müşteriAdı' is 'musteri_adi'): a short word only as a whole word ('ad' is no 'adres').
TR_WHO = re.compile(r"(?<![a-z])(?:adi?|isim|ismi)(?![a-z])|soyad|sahibi|unvan|hitap|cinsiyet")
TR_NOT_WHO = re.compile(r"asistan|temsilci|urun|kampanya|sirket|marka|sube|kurum")
TR_CALL_DATA = re.compile(r"dogum|tarih|kart|borc|tutar|asgari|odeme|hesap|kimlik|tckn|telefon|adres|sifre|parola|cevap|yanit|vade|"
                          r"ekstre|bakiye|taksit|gecik|numara|posta|bugun|simdi|saat|zaman|gun|(?<![a-z])(?:tc|tel|gsm|cep|no|son|hane|kod)(?![a-z])")
# The holder of a card or account, with the thing held ('account_holder', 'kart_sahibi'), on the folded name.
HOLDER = re.compile(r"(?:(?:card|account|kart|hesap)_?)?(?:holder|sahibi)")
# Placeholders the policy uses for the facts it reads back; a call variable of that name is not filled into the policy.
FACT_TOKENS = {"amount", "floor", "deadline", "date", "day", "weekday", "product", "time", "next_business_day"}


def _is_who(name):
    folded = fold(re.sub("(?<=[a-z0-9\u00e7\u011f\u0131\u00f6\u015f\u00fc])(?=[A-Z\u00c7\u011e\u0130\u00d6\u015e\u00dc])", "_", name))
    if NOT_WHO.search(name) or TR_NOT_WHO.search(folded):
        return False
    held = HOLDER.sub("_", folded)
    if held != folded:
        # Whose a value is: 'kart_sahibi' is who, 'kart_sahibi_dogum_tarihi' the holder's date of birth.
        return bool(WHO.search(held) or TR_WHO.search(held) or not (CALL_DATA.search(held) or TR_CALL_DATA.search(held)))
    return bool(WHO.search(name) or TR_WHO.search(folded) or not (CALL_DATA.search(name) or TR_CALL_DATA.search(folded)))


def who_variables(spec):
    """The call variables that say who this call is for."""
    now = spec.get("now_variable")
    return [v for v in spec.get("call_variables") or [] if v != now and _is_who(v)]


def _tool_name(key, api):
    """A tool_descriptions key as the name the compiler gives the tool: a path or 'METHOD /path' of an operation becomes that
    operation's tool name (its role, else compile.extra_tools' name), and so does the contract's own name for it
    (x-contract-operation-id) or the tool name in another case ('smsGonder'); anything else its last path segment."""
    from .compile import HTTP_METHODS, TOOL_NAMES, _find, _tool_base, extra_tools
    paths = (api.get("paths") if isinstance(api, dict) else None) or {}
    if not paths:
        return str(key).strip().strip("/").split("/")[-1]
    tools = {at: name for name, at in extra_tools(api).items()}
    tools.update({_find(api, t): t for t in TOOL_NAMES if _find(api, t)[0]})
    m = re.fullmatch(r"\s*(?:([A-Za-z]+)\s+)?(/\S*)\s*", str(key))
    if m and isinstance(paths.get(m.group(2)), dict):
        for method in [m.group(1).lower()] if m.group(1) else HTTP_METHODS:
            if (m.group(2), method) in tools:
                return tools[(m.group(2), method)]
    for (path, method), name in tools.items():
        if str(key).strip() in (paths[path][method].get("x-contract-operation-id"), paths[path][method].get("operationId")):
            return name
    base = _tool_base(key)
    return base if base in tools.values() else str(key).strip().strip("/").split("/")[-1]


def normalize_spec(spec, api):
    """Coerce a model-written spec into the types the compiler and facts code expect. Idempotent."""
    spec = copy.deepcopy(spec) if isinstance(spec, dict) else {}
    spec["call_variables"] = _names(spec.get("call_variables"))
    for key in ("language", "now_variable", "opening_line"):
        if spec.get(key) is not None and not isinstance(spec[key], str):
            spec[key] = _text(spec[key])
    if spec.get("language"):
        spec["language"] = language_name(spec["language"]) or spec["language"]
    now = spec.get("now_variable")
    if isinstance(now, str) and now and now not in spec["call_variables"] and \
            not any(re.search(r"now|date|time|today|clock", v, re.I) for v in spec["call_variables"]):
        # Raw material often says only "today"; the clock variable then has to be added, not guessed twice.
        spec["call_variables"].append(now)
    call_vars = set(spec["call_variables"])
    if spec.get("opening_line"):
        # A brief's single-brace {first_name} would otherwise be spoken literally.
        spec["opening_line"] = _call_templates(spec["opening_line"], call_vars)
    who = set(who_variables(spec))
    identity = spec.get("identity") if isinstance(spec.get("identity"), dict) else {}
    questions = []
    for q in identity.get("questions") or []:
        if isinstance(q, dict):
            questions.append({k: _call_templates(_text(v), who) if k in ("ask", "answer_format") else _text(v) for k, v in q.items()})
        elif q not in (None, ""):
            questions.append({"field": str(q), "ask": "", "answer_format": ""})
    identity["questions"] = questions
    limit = fold(identity.get("max_wrong_answers") or "").strip()
    limit = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5"}.get(limit.split(" ")[0], limit)
    if not re.search(r"\d", limit):
        limit = re.sub(r"\b(bir|iki|uc|dort|bes)\b", lambda m: TR_NUMBERS[m.group(1)], limit)
    limit = re.search(r"\d+", limit)
    identity["max_wrong_answers"] = int(limit.group(0)) if limit and int(limit.group(0)) > 0 else None
    spec["identity"] = identity
    calendar = spec.get("calendar") if isinstance(spec.get("calendar"), dict) else {}
    days = weekdays(calendar.get("business_weekdays"))
    calendar["business_weekdays"] = days or WEEKDAYS[:5]
    convention = fold(calendar.get("next_weekday") or "").strip()
    calendar["next_weekday"] = ("following_week" if re.search(r"follow|calendar|week after|next week|haftaya|(?:gelecek|sonraki|takvim) hafta", convention) else
                                "coming" if re.search(r"coming|occurr|soonest|first|en yakin|\bilk\b|\bgelen\b", convention) else "")
    holidays = []
    for h in calendar.get("holidays") or []:
        if isinstance(h, dict):
            holidays.append({"date": str(h.get("date", ""))[:10], "name": str(h.get("name") or "bank holiday")})
        elif isinstance(h, str):
            m = re.search(r"\d{4}-\d{2}-\d{2}", h)
            holidays.append({"date": m.group(0) if m else h, "name": h.replace(m.group(0), "").strip(" :-–()") or "bank holiday" if m else "bank holiday"})
    calendar["holidays"] = holidays
    rule = fold(calendar.get("closed_day_rule") or "")
    calendar["closed_day_rule"] = ("previous_business_day" if re.search(r"previous|prior|before|earlier|onceki|one cek", rule) else
                                   "next_business_day" if re.search(r"next|following|after|later|sonraki|ertesi|takip eden|izleyen", rule) else
                                   "ask_again" if re.search(r"ask|another|other|again|baska|tekrar|yeniden|\bsor(?:ar|ulur|mali)\b", rule) else "none")
    earliest = fold(calendar.get("earliest_promise_day") or "")
    calendar["earliest_promise_day"] = ("tomorrow" if re.search(r"tomorrow|next day|after today|not today|later than today|yarin|ertesi gun|"
                                                                r"bugunden sonra|bugun (?:degil|olamaz|verilemez)", earliest) else "today")
    spec["calendar"] = calendar
    account = spec.get("account") if isinstance(spec.get("account"), dict) else {}
    types = _product_types(api, account.get("list_field"), account.get("type_field"))
    for key in ("floor_field_by_type", "spoken_name_by_type"):
        account[key] = _by_type(account.get(key), types)
    # The facts code tells a map that covers one type from one whose key is a renamed type.
    account["product_types"] = types
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
        listed = band.get("product_types")
        listed = [listed] if isinstance(listed, str) and listed else listed if isinstance(listed, list) else []
        band["product_types"] = [str(t) for t in listed if t not in (None, "")]
        if band.get("floor_field_by_type") not in (None, "", {}):
            band["floor_field_by_type"] = _by_type(band.get("floor_field_by_type"), band["product_types"] or types)
        else:
            band.pop("floor_field_by_type", None)
        if not isinstance(band.get("deadline"), dict):
            band["deadline"] = {"type": "none", "count": 0, "date": ""}
        kind = str(band["deadline"].get("type") or "").lower()
        # This month's or next month's end, and this week's or next week's last business day, map to their kinds;
        # 'months after today', 'within a week' or a count stay as written (unknown: 'see policy').
        words = set(re.split(r"[^a-z0-9]+", kind))
        business = re.search(r"business|working|work_day|workday", kind)
        if words & {"end", "last", "final"} and not words & {"after", "within"} and not re.search(r"\d", kind):
            nxt = bool(words & {"next", "following"})
            if "month" in words:
                band["deadline"]["type"] = ("last_business_day_of" if business else "end_of") + ("_next_month" if nxt else "_month")
            elif "week" in words:
                band["deadline"]["type"] = "last_business_day_" + ("next_week" if nxt else "this_week")
        # The product's own date (a statement's due date), however the reader spelled the type.
        if band["deadline"].get("field") and (re.search(r"field|due|product|statement", kind)
                                              or (kind == "fixed_date" and not band["deadline"].get("date"))):
            band["deadline"]["type"] = "product_field"
        if band["deadline"].get("closed_day"):
            band["deadline"]["closed_day"] = ("next_business_day" if re.search(r"next|after|forward|following|sonraki|ilk", fold(band["deadline"]["closed_day"]))
                                              else "previous_business_day")
        roll = str(band["deadline"].get("roll_forward") or "").lower()
        band["deadline"]["roll_forward"] = ("today_or_earlier" if re.search(r"today|earlier|passed|past", roll)
                                            else "before_first_promise_day" if re.search(r"first|before|earliest|promise", roll) else "")
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
            name = _tool_name(key, api)
            if section == "tool_descriptions":
                fixed[name] = _text(item)
            else:
                fixed[name] = {str(f): _text(h) for f, h in item.items()} if isinstance(item, dict) else {}
        spec[section] = fixed
    policy = spec.get("policy") if isinstance(spec.get("policy"), dict) else {"after_verification": _text(spec.get("policy"))}
    # Seen live: a read wrote "Ask 'Am I speaking with {title} {last_name}?'", the platform filled nothing in and the agent
    # asked every customer for the example name in the brief. Text the identity phase sees (its own policy, and the
    # precedence and closing rules in the system prompt) gets only who the call is for; the text after verification any
    # call variable except the clock and one named like a read-back placeholder ('<date>', '<amount>').
    after = set(v for v in call_vars if v != now and v.lower() not in FACT_TOKENS)
    spec["policy"] = {k: _call_templates(_text(v), after if k == "after_verification" else who) for k, v in policy.items()}
    return spec
