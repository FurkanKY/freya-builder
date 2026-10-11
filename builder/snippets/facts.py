# Runs inside a Freya code node. The compiler prepends `SPEC_JSON = "..."` (the bank spec).
# Only json, re and datetime are verified in the sandbox. Never raise; always write every output.
import json
import re
import datetime

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _spec():
    try:
        return json.loads(SPEC_JSON)
    except Exception:
        return dict()


def _today(spec):
    """The call's clock: ISO (T or space, optional seconds, Z or offset), YYYY/MM/DD, or day-first DD/MM/YYYY or DD.MM.YYYY."""
    raw = str(vars.get(spec.get("now_variable") or "now") or "").strip()
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[T ,]+(\d{1,2}):(\d{2}))?", raw)
    if m:
        y, mo, d, h, mi = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
    else:
        m = re.search(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})(?:[T ,]+(\d{1,2}):(\d{2}))?", raw)
        if not m:
            return None
        d, mo, y, h, mi = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
    try:
        return datetime.datetime(int(y), int(mo), int(d), int(h or 0), int(mi or 0))
    except Exception:
        return None


def _calendar(spec):
    cal = spec.get("calendar") or dict()
    names = cal.get("business_weekdays") or WEEKDAYS[:5]
    lowered = [str(n).strip().lower()[:3] for n in (names if isinstance(names, list) else [names])]
    workdays = set(i for i, d in enumerate(WEEKDAYS) if d.lower()[:3] in lowered)
    if not workdays:
        workdays = set(range(5))
    holidays = dict()
    for h in cal.get("holidays") or []:
        if isinstance(h, dict):
            holidays[str(h.get("date", ""))[:10]] = str(h.get("name") or "bank holiday")
        else:
            holidays[str(h)[:10]] = "bank holiday"
    return workdays, holidays


def _is_business(day, workdays, holidays):
    return day.weekday() in workdays and day.isoformat() not in holidays


def _next_business(day, workdays, holidays, include=False):
    d = day if include else day + datetime.timedelta(days=1)
    for _ in range(400):
        if _is_business(d, workdays, holidays):
            return d
        d = d + datetime.timedelta(days=1)
    return None


def _previous_business(day, workdays, holidays):
    d = day - datetime.timedelta(days=1)
    for _ in range(400):
        if _is_business(d, workdays, holidays):
            return d
        d = d - datetime.timedelta(days=1)
    return None


def _nth_business_after(day, n, workdays, holidays):
    d, count = day, 0
    for _ in range(800):
        d = d + datetime.timedelta(days=1)
        if _is_business(d, workdays, holidays):
            count += 1
            if count >= n:
                return d
    return None


def _last_business_of_week(day, workdays, holidays):
    start = day - datetime.timedelta(days=day.weekday())
    best = None
    for i in range(7):
        d = start + datetime.timedelta(days=i)
        if _is_business(d, workdays, holidays):
            best = d
    return best


def _deadline(rule, today, workdays, holidays):
    if not isinstance(rule, dict):
        return None
    kind = str(rule.get("type") or "")
    try:
        n = int(rule.get("count") or 0)
    except Exception:
        n = 0
    if kind == "business_days_after_today" and n > 0:
        return _nth_business_after(today, n, workdays, holidays)
    if kind == "calendar_days_after_today" and n >= 0:
        return today + datetime.timedelta(days=n)
    if kind == "fixed_date":
        try:
            return datetime.date.fromisoformat(str(rule.get("date"))[:10])
        except Exception:
            return None
    if kind in ("end_of_month", "last_business_day_of_month"):
        first = (today.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        last = first - datetime.timedelta(days=1)
        if kind == "last_business_day_of_month":
            while not _is_business(last, workdays, holidays) and last > today:
                last = last - datetime.timedelta(days=1)
        return last
    return None


def _label(d):
    return d.isoformat() + " (" + WEEKDAYS[d.weekday()] + ", " + str(d.day) + " " + d.strftime("%B") + " " + str(d.year) + ")"


def _parse_products(spec):
    acc = spec.get("account") or dict()
    field = acc.get("list_field") or "products"
    # The api_request node's result is flattened under the NODE name (load_account_response...), seen live;
    # the mapped variable and the tool name are tried as well.
    candidates = [vars.get("account_products")] + [vars.get(k) for k in list(vars.keys()) if str(k).endswith("_response.data." + field)]
    for raw in candidates:
        value = raw
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except Exception:
                try:
                    value = json.loads(value.replace("'", '"').replace("True", "true").replace("False", "false").replace("None", "null"))
                except Exception:
                    value = None
        if isinstance(value, list) and value and all(isinstance(p, dict) for p in value):
            return value
    # Flattened keys such as load_account_response.data.products.0.past_due; one source only, the fullest.
    sources = dict()
    pattern = re.compile(r"^(account_products|\w+_response\.data\." + re.escape(field) + r")[.\[](\d+)\]?\.(\w+)$")
    for key in list(vars.keys()):
        m = pattern.search(str(key))
        if m:
            sources.setdefault(m.group(1), dict()).setdefault(int(m.group(2)), dict())[m.group(3)] = vars.get(key)
    if not sources:
        return []
    best = sorted(sources.items(), key=lambda kv: (-len(kv[1]), not kv[0].startswith("load_account"), kv[0]))[0][1]
    return [best[i] for i in sorted(best)]


def _num(value):
    try:
        return float(value)
    except Exception:
        return None


def _floor_of(product, rule, amount_field):
    """The lowest acceptable amount: a product field, 'N%' or 'N% of <field>' (rounded up to the cent), or a fixed number."""
    if rule is None or rule == "":
        return None, None
    if isinstance(rule, (int, float)) and not isinstance(rule, bool):
        return "fixed amount", float(rule)
    text = str(rule).strip()
    m = re.match(r"^(\d+(?:\.\d+)?)\s*%(?:\s*of\s*(\w+))?$", text)
    if m:
        base = _num(product.get(m.group(2) or amount_field))
        if base is None:
            return text, None
        label = text if m.group(2) else text + " of " + amount_field
        return label, _ceil_cents(base * float(m.group(1)) / 100.0)
    if text not in product and _num(text) is not None:
        return "fixed amount", _num(text)
    return text, product.get(text)


def _ceil_cents(value):
    cents = int(value * 100)
    if cents < value * 100 - 1e-6:
        cents += 1
    return cents / 100.0


def _money(value):
    v = _num(value)
    if v is None:
        return str(value)
    return ("%.2f" % v).rstrip("0").rstrip(".") if v != int(v) else str(int(v))


def _for_type(mapping, kind):
    # Exact product type first, then a case-insensitive match, then a catch-all entry.
    if not isinstance(mapping, dict):
        return mapping if isinstance(mapping, str) else None
    if kind in mapping:
        return mapping[kind]
    for k, v in mapping.items():
        if str(k).strip().lower() == kind.strip().lower():
            return v
    for k in ("*", "all", "any", "default"):
        if k in mapping:
            return mapping[k]
    if len(mapping) == 1:
        return list(mapping.values())[0]
    return None


def _spoken(template, product):
    out = str(template or product.get("type") or "product")
    for k, v in product.items():
        out = out.replace("<" + str(k) + ">", str(v))
    return out


def _day_line(d, today, workdays, holidays, deadlines):
    text = d.isoformat() + " " + WEEKDAYS[d.weekday()]
    if d < today:
        text += ": in the PAST"
    elif _is_business(d, workdays, holidays):
        text += ": business day"
    else:
        text += ": HOLIDAY (" + holidays[d.isoformat()] + "), NOT a business day" if d.isoformat() in holidays else ": weekend, NOT a business day"
        prv = _previous_business(d, workdays, holidays)
        if prv and prv >= today:
            text += "; previous business day " + prv.isoformat() + " " + WEEKDAYS[prv.weekday()]
        nxt = _next_business(d, workdays, holidays)
        if nxt:
            text += "; next business day " + nxt.isoformat() + " " + WEEKDAYS[nxt.weekday()]
            late = [name for name, dl in deadlines if nxt > dl]
            if late:
                text += " (AFTER the deadline of " + ", ".join(late) + ")"
    inside = [name for name, dl in deadlines if d <= dl]
    after = [name for name, dl in deadlines if d > dl]
    if inside:
        text += "; on or before the deadline of " + ", ".join(inside)
    if after:
        text += "; AFTER the deadline of " + ", ".join(after) + " (" + "; ".join(name + " deadline " + dl.isoformat() + " " + WEEKDAYS[dl.weekday()] for name, dl in deadlines if d > dl) + ")"
    return text


MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
UNITS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
         "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9}
TEENS = {"ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
         "eighteen": 18, "nineteen": 19, "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14,
         "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18, "nineteenth": 19}
TENS = {"twenty": 20, "thirty": 30, "twentieth": 20, "thirtieth": 30}
ORDINAL_WORDS = set(["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "twentieth", "thirtieth"]
                    + [w for w in TEENS if w.endswith("th")])


def _day_number(tokens):
    """(day of month, explicit) from digits or English number words; None when no day number is said."""
    for i, tok in enumerate(tokens):
        m = re.match(r"^(\d{1,2})(st|nd|rd|th)?$", tok)
        value, ordinal = None, False
        if m:
            value, ordinal = int(m.group(1)), bool(m.group(2))
        elif tok in TENS:
            value = TENS[tok]
            ordinal = tok.endswith("th")
            if i + 1 < len(tokens) and tokens[i + 1] in UNITS and not ordinal:
                value += UNITS[tokens[i + 1]]
                ordinal = tokens[i + 1] in ORDINAL_WORDS
        elif tok in TEENS or tok in UNITS:
            value = TEENS.get(tok) or UNITS.get(tok)
            ordinal = tok in ORDINAL_WORDS
        if value is None or not 1 <= value <= 31:
            continue
        before = tokens[i - 1] if i > 0 else ""
        near = tokens[max(0, i - 2):i + 4]
        # Amounts and chat also contain numbers: a day needs an ordinal, "the", or a month next to it.
        if ordinal or before == "the" or any(w in MONTHS for w in near):
            return value
    return None


def _resolve_day(words, today):
    """Candidate dates for the customer's own words, relative to the call's today (not the server clock)."""
    text = re.sub(r"[^a-z0-9 ]", " ", str(words).lower().replace("-", " "))
    tokens = text.split()
    if not tokens:
        return []
    joined = " " + " ".join(tokens) + " "
    if " day after tomorrow " in joined:
        return [today + datetime.timedelta(days=2)]
    if " tomorrow " in joined:
        return [today + datetime.timedelta(days=1)]
    if " today " in joined or " tonight " in joined:
        return [today]
    month = None
    for i, tok in enumerate(tokens):
        if tok in MONTHS and (tok != "may" or _day_number(tokens[max(0, i - 3):i + 4])):
            month = MONTHS.index(tok) + 1
    day = _day_number(tokens)
    if day:
        y, mo = today.year, month or today.month
        for _ in range(3):
            try:
                d = datetime.date(y, mo, day)
            except Exception:
                d = None
            if d and d >= today:
                return [d]
            if month:
                y += 1
            else:
                y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
        return []
    wd = [i for i, d in enumerate(WEEKDAYS) if d.lower() in tokens]
    if len(wd) != 1:
        # "I can't pay right now" is about today, like "today", when the words name no other day.
        if not wd and not month and re.search(r" (right now|now|at the moment|immediately|straight away|this minute) ", joined):
            return [today]
        return []
    coming = today + datetime.timedelta(days=(wd[0] - today.weekday()) % 7)
    if " after next " in joined:
        return [coming + datetime.timedelta(days=7)]
    if " next week " in joined:
        start = today - datetime.timedelta(days=today.weekday()) + datetime.timedelta(days=7)
        return [start + datetime.timedelta(days=wd[0])]
    if " next " in joined:
        # "next Friday" is the coming one for some callers and the one of next week for others.
        first = coming if coming > today else coming + datetime.timedelta(days=7)
        return [first, first + datetime.timedelta(days=7)]
    if coming == today:
        return [today, today + datetime.timedelta(days=7)]
    return [coming]


VAGUE_DAY = set(["week", "weekend", "fortnight", "month", "year", "payday", "salary", "wage", "pension", "paycheck", "paycheque",
                 "end", "beginning", "start", "mid", "middle", "later", "soon", "next", "after", "before", "until", "till"]
                + [m for m in MONTHS if m] + [d.lower() for d in WEEKDAYS])


def _named_day(today, workdays, holidays, deadlines):
    """The customer's words for a day, copied by extraction, resolved and checked against the calendar here, then cleared."""
    raw = str(vars.get("named_day_words") or "").strip()
    if not raw or raw == "none":
        return
    vars["named_day_words"] = "none"
    try:
        days = _resolve_day(raw, today)
    except Exception:
        days = []
    if not days:
        return
    lines = [_day_line(d, today, workdays, holidays, deadlines) for d in days]
    rule = str((_spec().get("calendar") or dict()).get("closed_day_rule") or "none")
    within = all(days[0] <= dl for _, dl in deadlines) if days else False
    if len(days) == 1 and days[0] >= today and within and not _is_business(days[0], workdays, holidays):
        nxt, prv = _next_business(days[0], workdays, holidays), _previous_business(days[0], workdays, holidays)
        if rule == "next_business_day" and nxt:
            lines[0] += ". For this the policy says to offer the next business day: " + _label(nxt)
        elif rule == "previous_business_day" and prv and prv >= today:
            lines[0] += ". For this the policy says to offer the previous business day: " + _label(prv)
        elif rule == "ask_again":
            lines[0] += ". For this the policy says to ask for another day"
    said = [d for d in WEEKDAYS if re.search(r"\b" + d.lower() + r"\b", raw.lower())]
    clash = ""
    if said and len(days) == 1 and WEEKDAYS[days[0].weekday()] not in said:
        clash = " The customer said " + said[0] + ", but that date is a " + WEEKDAYS[days[0].weekday()] + "; ask which day they mean."
    vars["named_day_facts"] = ("The day in the customer's last message ('" + raw[:60] + "'), resolved by code from today's date: "
                               + (" OR ".join(lines) + ". It can mean either day; if it matters, ask which one." if len(lines) > 1 else lines[0] + ".")
                               + clash + " If the customer named only a vague period, or no day, ignore this line.")


NAME_STOP = set(["the", "a", "an", "your", "my", "of", "with", "ending", "in", "on", "number", "account", "product", "for", "and",
                 "to", "or", "no", "not", "one", "that", "this", "it", "pay", "payment"])
ALL_WORDS = set(["all", "everything", "every", "none", "neither", "nothing", "any", "anything"])
EXCEPT_WORDS = set(["except", "but", "apart", "besides", "other", "than", "excluding", "without"])


def _tokens(text):
    out = set()
    for tok in re.findall(r"[a-z0-9]+", str(text).lower()):
        out.add(tok[:-1] if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss") else tok)
    return out


def _refused_ids(words, infos):
    """Product ids for the customer's words: a token only one product has picks it; a shared one ('loan') picks all its owners."""
    said = _tokens(words)
    if not said or not infos:
        return []
    owners = dict()
    for pid, toks in infos:
        for t in toks:
            owners.setdefault(t, []).append(pid)
    distinct = [pid for pid, toks in infos if any(t in said and len(owners[t]) == 1 for t in toks)]
    hits = list(distinct)
    for t in said:
        group = owners.get(t) or []
        if len(group) > 1 and not any(g in distinct for g in group):
            hits += [g for g in group if g not in hits]
    if hits and said & ALL_WORDS and said & EXCEPT_WORDS:
        # "all except the card" refuses the others.
        return [pid for pid, _ in infos if pid not in hits]
    if hits:
        return [pid for pid, _ in infos if pid in hits]
    if said & ALL_WORDS or ("both" in said and len(infos) == 2) or len(infos) == 1:
        return [pid for pid, _ in infos]
    return []


NO_VALUE = set(["", "none", "nothing", "n/a", "na", "null", "nil", "no refusal", "nothing refused", "none refused", "not applicable",
                "no product", "not refused", "no product refused", "none of the product refused", "yes", "ok"])
NOT_REFUSAL = set(["accept", "accepted", "agree", "agreed", "applicable", "confirm", "confirmed"])
BARE_NO = set(["no", "nope", "nah", "not", "never", "won", "t", "can", "cannot", "don", "do", "doesn", "refuse", "refused", "refuse",
               "refusal", "flat", "flatly", "decline", "declined", "pay", "paying", "it", "that", "this", "i", "will", "want", "to",
               "way", "now", "sorry", "afford", "the", "a", "offer", "proposal", "customer", "say", "said", "just",
               "those", "these", "them", "either", "both", "of"])


def _no_value(raw):
    """True for the extraction's 'nothing refused' value in any spelling ('None.', 'nothing', 'No refusals', 'N/A (accepted)')."""
    key = " ".join(t for t in re.findall(r"[a-z/]+", str(raw or "").lower().replace("n't", " not").replace("n’t", " not")))
    words = [t[:-1] if len(t) > 3 and t.endswith("s") and not t.endswith("ss") else t for t in key.split(" ") if t]
    key = " ".join(words)
    if key in NO_VALUE or set(words) & NOT_REFUSAL:
        return True
    if words and words[0] in ("yes", "ok", "okay", "sure", "fine", "yeah", "yep", "alright", "correct"):
        # 'yes, credit card' is an acceptance written into the refusal field, not a refusal.
        return True
    if re.search(r"\b(no|not|none|nothing|never)\b\W+(\w+\W+)?refus", key):
        return True
    return bool(words) and words[0] in ("none", "nothing") and (len(words) < 2 or words[1] != "of")


def _bare_no(raw):
    """A refusal that names no product ('No.', 'I won't pay that'): it answers what the assistant just proposed."""
    words = _tokens(raw)
    return bool(words) and words <= BARE_NO


def _ids(raw, infos):
    return [] if _no_value(raw) else _refused_ids(raw, infos)


def _count_refusals(plans, day_named=False, named_date=None, today_iso=None, recorded=None):
    """Counts, per product, the refused proposals the assistant actually made, then clears the extracted words.

    The first ask covers every product once: a product refused in answer to it gets count 1, never more. After that a
    refusal adds one only for the products the assistant last proposed, so a repeated "none of them" during one
    product's proposal does not use up the proposals of products not offered yet. A product first refused after the
    first ask starts at attempt 1, unless the customer had given it a day or an amount of their own: then that refusal
    is its answer to the first ask. Returns (counts, changed ids, ids the customer gave a day for in this answer, whether
    the customer only asked a question back while the first ask to pay every product was still open).
    """
    asked_back = str(vars.get("asked_back") or "").strip(" .'\"").lower() in ("yes", "true")
    try:
        counts = json.loads(str(vars.get("refusal_counts") or "{}"))
        counts = counts if isinstance(counts, dict) else dict()
    except Exception:
        counts = dict()
    try:
        own = json.loads(str(vars.get("own_offer_products") or "[]"))
        own = own if isinstance(own, list) else []
    except Exception:
        own = []
    infos = [(pl[0], pl[4]) for pl in plans]
    all_ids = [pl[0] for pl in plans]
    k_of = lambda pid: int(counts.get(pid) or 0)
    recorded = recorded or dict()
    done = lambda pid: bool(set(recorded.get(pid) or []) & set(["add_note", "create_promise"]))
    try:
        agreed = json.loads(str(vars.get("agreed_products") or "{}"))
        agreed = agreed if isinstance(agreed, dict) else dict()
    except Exception:
        agreed = dict()
    # The first ask is open while no product has a count or a day or amount of the customer's own.
    first_open = not any(k_of(pid) for pid in all_ids) and not own
    closed = str(vars.get("first_ask_closed") or "") == "yes"
    raw = str(vars.get("refused_products") or "").strip()
    asked = _ids(str(vars.get("proposed_products") or ""), infos)
    dated_now = _ids(str(vars.get("dated_products") or ""), infos)
    accepted = [] if asked_back and first_open else _ids(str(vars.get("accepted_products") or ""), infos)
    # An acceptance is for the proposal the assistant made. Seen in a review: 'all', 'everything' or 'the loan' agreed products
    # whose proposal was never made. Without a proposed product, only the first product with a proposal open, in bank order.
    if asked:
        accepted = [pid for pid in accepted if pid in asked]
    elif len(accepted) > 1 and not first_open:
        open_now = [pid for pid in all_ids if pid in accepted and pid not in agreed and not done(pid)
                    and (0 < k_of(pid) <= _total(plans[all_ids.index(pid)]) or (k_of(pid) == 0 and pid not in own))]
        accepted = open_now[:1]
    accepted = [pid for pid in accepted if not done(pid)]
    # A yes to attempt 1 of a product the first ask already covered is that attempt accepted, not a day of the customer's own.
    late_yes = [pid for pid in accepted if k_of(pid) == 0 and pid not in own and (not first_open or closed)
                and not (asked and set(asked) == set(all_ids))]
    for pid in dated_now:
        if k_of(pid) == 0 and pid not in own and pid not in late_yes and not done(pid):
            own.append(pid)
    changed = []
    fresh = []
    refused_now = []
    try:
        days_of = json.loads(str(vars.get("own_offer_days") or "{}"))
        days_of = days_of if isinstance(days_of, dict) else dict()
    except Exception:
        days_of = dict()
    if named_date:
        for pid in _ids(str(vars.get("dated_products") or ""), infos):
            days_of[pid] = named_date
    if not _no_value(raw):
        ids = _refused_ids(raw, infos)
        if not ids and _bare_no(raw):
            open_ids = [pl[0] for pl in plans if 0 < k_of(pl[0]) <= _total(pl) and pl[0] not in agreed]
            ids = asked or (open_ids if len(open_ids) == 1 else [])
        first_ask = first_open and (not asked or set(asked) == set(all_ids))
        if first_ask and dated_now and set(ids) - set(dated_now):
            ids = [pid for pid in ids if pid not in dated_now]
        if first_ask and day_named and not (named_date and named_date == today_iso) and ids and set(ids) < set(all_ids):
            # "I can pay the card tomorrow, not the loans": the day is for the products not refused, even when the
            # dated_products extraction missed it. Seen live: the closing phase depends on knowing this.
            # Not today: "I can't pay today, not the card or the loan" refuses the first ask's own day. Seen in a chat run:
            # today was kept as the car loan's day and read back as the customer's promise.
            for pid in all_ids:
                if pid not in ids and k_of(pid) == 0 and pid not in own:
                    own.append(pid)
                    if named_date:
                        days_of.setdefault(pid, named_date)
        if not first_ask and not asked and len(ids) > 1:
            # Not known what was proposed: a group refusal counts only for the product being worked on, in bank order.
            working = [pid for pid in all_ids if pid in ids and pid not in agreed and 0 < k_of(pid) <= _total(plans[all_ids.index(pid)])]
            # Products never counted and never offered by the customer are refusing the first ask, asked again for them.
            # Seen live: "I can pay the card tomorrow", then "can you pay the loans today?", "no": nothing was counted.
            fresh = [pid for pid in all_ids if pid in ids and k_of(pid) == 0 and pid not in own]
            ids = fresh + working[:1]
        refused_now = list(ids)
        for pid in ids:
            k = k_of(pid)
            if first_ask or pid in fresh:
                new = max(k, 1)
            elif asked and pid not in asked:
                new = k
            elif k == 0:
                new = 1 if pid in own else 2
            else:
                new = k + 1
            if new != k:
                counts[pid] = new
                changed.append(pid)
    elif first_open and day_named and dated_now and (not asked or set(asked) == set(all_ids)):
        # "Can you pay all of them today?" "I can pay the card tomorrow": the products the answer leaves out are not
        # paid today either. Each is counted once for the first ask, so its plan starts at attempt 1 and today is not
        # asked again.
        for pid in all_ids:
            if pid not in dated_now and k_of(pid) == 0 and pid not in own:
                counts[pid] = 1
                changed.append(pid)
    # "Why do you need all of them today?" right after the first ask: no answer, so nothing is counted; seen in a chat run,
    # the model then asked about today again. The plan names attempt 1 instead, and remembers that the first ask is closed.
    offered_day = day_named and not (named_date and named_date == today_iso)
    question = (asked_back and first_open and not closed and bool(asked) and set(asked) == set(all_ids) and not changed
                and not dated_now and not own and not offered_day)
    if question:
        vars["first_ask_closed"] = "yes"
    # A product whose proposal the customer accepted is agreed: seen in a review, a card that accepted its attempt 1 stayed
    # pending, was proposed again once the loan was done and held the car loan back. Only a refusal counted for it takes it
    # back; a group refusal while another product is proposed does not.
    for pid in changed:
        if pid in agreed:
            agreed.pop(pid, None)
            days_of.pop(pid, None)
    for pid in accepted + [pid for pid in dated_now if k_of(pid) > 0]:
        if pid in refused_now or done(pid):
            continue
        if pid in late_yes:
            counts[pid] = 1
            agreed[pid] = 1
        elif k_of(pid) == 0 and pid not in own:
            own.append(pid)
            if named_date:
                days_of.setdefault(pid, named_date)
        elif 0 < k_of(pid) <= _total(plans[all_ids.index(pid)]):
            agreed[pid] = k_of(pid)
    vars["accepted_products"] = "none"
    vars["agreed_products"] = json.dumps(agreed, sort_keys=True)
    vars["asked_back"] = "no"
    vars["first_ask_open"] = "no" if question or closed or own or any(int(counts.get(pid) or 0) for pid in all_ids) else "yes"
    vars["refused_products"] = "none"
    vars["proposed_products"] = "none"
    vars["dated_products"] = "none"
    vars["own_offer_products"] = json.dumps(own)
    vars["own_offer_days"] = json.dumps(days_of, sort_keys=True)
    vars["refusal_counts"] = json.dumps(counts, sort_keys=True)
    return counts, changed, dated_now, question, [pid for pid in accepted if pid in agreed]


def _var(key):
    """A tool result variable, flattened with dots as the engine keeps it (seen live) or nested."""
    if key in vars:
        return vars.get(key)
    node = vars
    for part in key.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    return node


def _recorded(ids):
    """Per product, the tools that already succeeded for it in this call, e.g. {"p2": ["add_note"]}. The engine keeps only each
    tool's last arguments (<tool>_args.<field>, seen live), so every run adds what it sees to a list kept in a variable.
    Seen live: a note written when a product reached STOP was written again by the closing node."""
    try:
        seen = json.loads(str(vars.get("recorded_calls") or "{}"))
        seen = seen if isinstance(seen, dict) else dict()
    except Exception:
        seen = dict()
    args = dict()
    for key in list(vars.keys()):
        m = re.match(r"^(\w+?)_args\.\w+$", str(key))
        if m:
            args.setdefault(m.group(1), []).append(vars.get(key))
        m = re.match(r"^(\w+?)_args$", str(key))
        if m and isinstance(vars.get(key), dict):
            args.setdefault(m.group(1), []).extend(vars.get(key).values())
    for tool, values in args.items():
        ok = str(_var(tool + "_response.data.ok") or "").strip().lower()
        code = str(_var(tool + "_status_code") or _var(tool + "_response.status_code") or "")
        if ok in ("false", "0", "no") or (not ok and not code.startswith("2")):
            continue
        for value in values:
            pid = str(value).strip()
            if pid in ids and tool not in seen.get(pid, []):
                seen.setdefault(pid, []).append(tool)
    vars["recorded_calls"] = json.dumps(seen, sort_keys=True)
    return seen


def _already(tools):
    """What a DONE product's line says about the tools already done for it; empty when none."""
    tools = [t for t in tools or [] if t != "create_promise"]
    if not tools:
        return ""
    return (" Already done for it in this call: " + ", ".join(tools) + " succeeded; do not call " + ", ".join(tools)
            + " for it again.")


def _total(plan):
    steps, allowed = plan[2], plan[3]
    return len(steps) if steps else (allowed if allowed is not None else 99)


def _plan_state(plans, counts, changed=(), own=(), details=None, recorded=None, day_named=False, dated=(), question=False,
                first_closed=False, agreed=None, accepted_now=()):
    recorded = recorded or dict()
    agreed = agreed or dict()
    pending_ids, accepted_names = [], []
    lines = []
    next_of = dict()
    first_of = dict()
    now = []
    pending, unasked, stopped, offered = [], [], [], []
    # Per product: the index of its line and the text naming its next proposal, so the product the NEXT STEP names
    # can be kept apart from the others.
    line_of, later = dict(), dict()
    first_done = bool(own) or question or first_closed or any(int(counts.get(pl[0]) or 0) for pl in plans)
    for pid, label, steps, allowed, _, floor in plans:
        k = int(counts.get(pid) or 0)
        text = pid + " " + label + ": refused " + str(k) + (" time" if k == 1 else " times")
        total = len(steps) if steps else allowed
        if "create_promise" in (recorded.get(pid) or []):
            # Whatever its count: a product with a recorded promise gets no more proposals.
            text += "; its promise is already recorded in this call: do not read it back or record it again"
        elif k == 0 and pid not in own and "add_note" in (recorded.get(pid) or []):
            # A note before any proposal is a dispute, a payment already made or another exception of the policy.
            text += "; its note is already written in this call: propose nothing for it"
        elif pid not in own and "add_note" in (recorded.get(pid) or []) and not (total is not None and k > total):
            # The same after the first ask was refused, the usual moment for a hardship or a dispute: seen in a review, the
            # product stayed queued and the NEXT STEP proposed to it again. It is done like a product at STOP.
            stopped.append(pid)
            text += "; its note is already written in this call: propose nothing for it"
        elif k == 0 and pid in own:
            offered.append(pid + " " + label)
            text += ("; the customer gave a day or an amount for it: handle that under the date and amount rules; its plan starts only"
                     " if the customer then refuses; its read-back comes once no product has a proposal left")
        elif k == 0:
            unasked.append(pid)
            text += "; nothing refused yet"
            if first_done and (steps or total):
                # "Not the card or the loan, but we can talk about the car loan": the first ask covered the car loan too.
                # Seen in a chat run: the model asked it again for the car loan alone. Its answer may still be a day of
                # the customer's own, so it is not counted; the line names the proposal that comes instead.
                first_of[pid] = pid + " " + label + ": attempt 1: " + (steps[0] if steps else "persuasion attempt 1 as the policy says")
                text += ("; the first ask already covered it, so do not ask it again for " + pid + ". Unless the customer"
                         " gives a day or an amount for it, its next proposal is attempt 1: "
                         + (steps[0] if steps else "persuasion attempt 1 as the policy says"))
                later[pid] = ("its next proposal is attempt 1:", "its next proposal, {}, is attempt 1:")
        elif pid in agreed and not (total is not None and k > total):
            offered.append(pid + " " + label)
            accepted_names.append(pid + " " + label)
            step = int(agreed.get(pid) or k)
            text += ("; after its attempt " + str(step) + (" (" + steps[step - 1] + ")" if steps and 0 < step <= len(steps) else "")
                     + " the customer agreed to pay it, as proposed or on a day they gave; settle it under the date and amount rules; no"
                     " new proposal for it unless the customer takes it back; its read-back comes once no product has a proposal left")
        elif total is not None and k > total:
            stopped.append(pid)
            text += " -> STOP: its " + str(total) + (" proposal after the first ask is" if total == 1 else " proposals after the first ask are") + " used; make no more payment proposals for " + pid + ", not its floor and not another date, and apply the policy for a product without a promise"
            if _already(recorded.get(pid)):
                text += "." + _already(recorded.get(pid)).rstrip(".")
            if pid in changed:
                # Seen live: after the last allowed full-amount proposal the model still offered the floor.
                # No figure inside a prohibition: a weak model repeats the number it reads.
                now.append("The customer has just refused the last proposal allowed for " + pid + " " + label + ". It is done: propose no amount"
                           " and no date for it any more.")
        elif steps:
            pending_ids.append(pid)
            pending.append(pid + " " + label + ": attempt " + str(k) + ": " + steps[k - 1])
            next_of[pid] = pending[-1]
            text += " -> next proposal for " + pid + ": attempt " + str(k) + ": " + steps[k - 1]
            later[pid] = ("next proposal for " + pid + ":", "next proposal for " + pid + ", {}:")
        else:
            pending_ids.append(pid)
            pending.append(pid + " " + label + ": persuasion attempt " + str(k) + (" of " + str(total) if total is not None else "") + " as the policy says")
            next_of[pid] = pending[-1]
            text += " -> next: persuasion attempt " + str(k) + (" of " + str(total) if total is not None else "") + " as the policy says"
            later[pid] = ("-> next:", "-> next, {}:")
        line_of[pid] = len(lines)
        lines.append(text + ".")
    # Seen live: told only what not to do, the model filled the gap with an offer of its own. Name the next step.
    propose = "NEXT STEP: your next message makes exactly this proposal and no other: "
    # Seen in a chat run: the customer refused one product and gave a day for another in one answer; the model read back
    # that day instead of making the named proposal. All promises are read back together at the end.
    days = [name for name in offered if name not in accepted_names]
    waits = ((" The day the customer gave for " + " and ".join(days) if days else " The proposal the customer accepted for "
              + " and ".join(accepted_names)) + (" and the proposal they accepted for " + " and ".join(accepted_names) if days and accepted_names else "")
             + (" wait" if days and accepted_names else " waits") + ": no read-back and no confirmation question for "
             + ("them" if days and accepted_names else "it") + " in this message.") if offered else ""
    order = [pl[0] for pl in plans]
    first_open = [pid for pid in order if pid in first_of]
    named = None
    if now and pending:
        named = pending_ids[0]
        now.append(propose + pending[0] + "." + waits)
    elif (stopped or accepted_now) and not pending and not unasked:
        now.append(_closing_step(offered, details))
    elif question and first_open:
        named = first_open[0]
        now.append("NEXT STEP: the first ask is made and is never asked again. Answer the customer's question in one short sentence"
                   " from the policy or the ACCOUNT FACTS (say so if you do not have that information), then in the same message make"
                   " exactly this proposal and no other: " + first_of[first_open[0]] + ". If what the customer said falls under a policy"
                   " exception (hardship, a dispute, a payment already made, a request for a person or for another plan), apply that"
                   " rule instead and propose nothing.")
    elif not (day_named and not dated):
        # A refusal was just counted: one product at a time, in bank order. Seen live: with two products refused
        # together, the model proposed to both in one message and gave the one-attempt product a second proposal.
        # Not when the customer gave a day in the same answer without naming a product: that day is checked first.
        # A product before it in bank order that nobody has answered for yet comes first; then nothing is named.
        nxt = [pid for pid in order if pid in changed and pid in next_of and pid not in dated]
        if nxt and not any(pid in unasked for pid in order[:order.index(nxt[0])]):
            named = nxt[0]
            now.append(propose + next_of[nxt[0]] + "." + waits)
        elif changed and not pending and first_open:
            named = first_open[0]
            # Seen in a chat run: after a product's STOP, a product the first answer left open had no step named.
            now.append(propose + first_of[first_open[0]] + "." + waits + " If the customer disputed " + first_open[0] + " or said it is"
                       " already paid, apply the policy for that instead and propose nothing for it.")
    if accepted_now and not named and not any(x.startswith("NEXT STEP") for x in now):
        # The customer accepted a proposal: the next product's proposal follows, one product at a time in bank order.
        if pending_ids:
            named = pending_ids[0]
            now.append(propose + pending[0] + "." + waits)
        elif first_open:
            named = first_open[0]
            now.append(propose + first_of[first_open[0]] + "." + waits)
    if named:
        # Seen in a chat run: the NEXT STEP named the card, the loan's line named its own next proposal, and the model made
        # both in one message. The policy goes through the products one by one.
        for pid, (old, new) in later.items():
            if pid != named and pid in line_of:
                lines[line_of[pid]] = lines[line_of[pid]].replace(old, new.format("only after " + named + " is settled and never in the"
                                                                                  " same message as " + named + "'s"), 1)
    return ("\n".join(now) + ("\n" if now else "")
            + "Refusals counted by code from the customer's answers: the first ask counts once for each product refused in answer to it,"
            " then each proposal the assistant made for a product and the customer flatly refused or evaded counts once for that product."
            " Make exactly the next proposal named here, and none after STOP; never repeat the first ask. A product with a recorded"
            " promise is done. The policy's own exceptions, such as hardship, come first.\n"
            + "\n".join(lines))


def _closing_step(offered, details=None):
    """One concrete next message for the turn after the last proposal; seen live, a list of don'ts was filled with an offer.
    `details` names, per offered product, the day the customer gave and the amount owed, so the read-back has its figures."""
    if offered:
        parts = []
        for name in offered:
            d = (details or dict()).get(name)
            parts.append(name + ((": " + d) if d else ": the day and the amount the customer gave"))
        return ("NEXT STEP: no product has a proposal left. Your next message is the read-back for " + "; ".join(parts)
                + ". Ask them to confirm it as the policy says. The read-back is the only amount and the only day in the message;"
                " nothing is proposed for any other product.")
    return ("NEXT STEP: no product has a proposal left. Your next message proposes no amount and no date: apply the policy for the"
            " products without a promise, then close the call.")


def _wrap_up(plans, counts, own, owed=None, details=None, recorded=None, agreed=None):
    """(True, product lines) when no product has a proposal left: each is at STOP or has a day or amount the customer gave,
    and at least one is at STOP. The workflow then leaves the persuasion plans behind for a closing node.
    `recorded` (from _recorded) keeps a promise or a note already written out of the steps still to do."""
    recorded = recorded or dict()
    agreed = agreed or dict()
    lines, stopped, offered, promised = [], 0, [], []
    for pid, label, steps, allowed, _, floor in plans:
        k = int(counts.get(pid) or 0)
        if "create_promise" in (recorded.get(pid) or []):
            promised.append(pid)
            lines.append(pid + " " + label + ": its promise is already recorded in this call (create_promise succeeded): do not read it"
                         " back or record it again.")
        elif k == 0 and pid in own:
            offered.append(pid + " " + label)
            lines.append(pid + " " + label + (owed or dict()).get(pid, "") + ": the customer offered a day or an amount for it. Settle it under the date and amount rules,"
                         " read it back and record it after the confirmation the policy asks for, unless its promise is already recorded.")
        elif "add_note" in (recorded.get(pid) or []) and not k > _total((pid, label, steps, allowed)):
            stopped += 1 if k else 0
            lines.append(pid + " " + label + ": its note is already written in this call (add_note succeeded): propose nothing for it"
                         " and do not write its note again.")
        elif pid in agreed and pid in own and k <= _total((pid, label, steps, allowed)):
            offered.append(pid + " " + label)
            lines.append(pid + " " + label + (owed or dict()).get(pid, "") + ": the customer accepted the proposal named in the NEXT STEP for it."
                         " Read it back and record it after the confirmation the policy asks for, unless its promise is already recorded.")
        elif k > _total((pid, label, steps, allowed)):
            stopped += 1
            lines.append(pid + " " + label + ": DONE. Every proposal allowed for it was made and refused: propose no amount and no date"
                         " for it. Apply the policy for a product without a promise." + _already(recorded.get(pid)))
        else:
            return False, "", ""
    if not stopped or not (offered or promised):
        # Every product refused: the negotiate node's closing step has passed live; the closing node adds nothing there.
        return False, "", ""
    if offered:
        step = _closing_step(offered, details) + " If the customer already confirmed, do the next of these steps instead."
    else:
        step = ("NEXT STEP: no product has a proposal left and every promise the customer gave is recorded. Your next message proposes"
                " no amount and no date: do the remaining closing steps in order, without repeating a tool call already done.")
    return True, ("\n".join(lines) + "\nWhen every product has its promise, or what the policy prescribes for a product without one,"
                  " close the call as the CLOSING TABLE says.\n" + step), step


AMOUNT_WORDS = ("hundred", "thousand", "half", "fifty", "twenty", "thirty", "forty", "sixty", "seventy", "eighty", "ninety",
                "ten", "eleven", "twelve", "fifteen")


def _amount_named(raw):
    """True when the extraction holds an amount of the customer's own ('300', 'two hundred', 'half of it')."""
    raw = str(raw or "").strip().lower()
    if raw.strip(" .'\"") in ("", "none", "n/a", "null", "no", "nothing"):
        return False
    return bool(re.search(r"\d", raw) or re.search(r"\b(" + "|".join(AMOUNT_WORDS) + r")\b", raw))


def _confirm_question(spec):
    """The brief's own words for asking to confirm a promise when its policy quotes them, else a plain question."""
    text = " ".join(str(v) for v in (spec.get("policy") or dict()).values())
    for m in re.finditer(r"['\"\u201c\u2018]([A-Z][^'\"\u201c\u201d\u2018\u2019{}<>\n]{2,80}\?)['\"\u201d\u2019]", text):
        if re.search(r"\bconfirm|\bcorrect\b|\bright\b", m.group(1), re.I):
            return m.group(1)
    return "Do you confirm?"


def _readback_line(spec, items):
    """The read-back said as a fixed line, with no model call, on the turn the last proposal is refused. `items` holds
    (spoken name, amount, date) for each product the customer gave a day for. English only: the line is written in English."""
    if not items or not str(spec.get("language") or "English").strip().lower().startswith("en"):
        return ""
    parts = [name + ", " + amount + " on " + WEEKDAYS[d.weekday()] + ", " + str(d.day) + " " + d.strftime("%B")
             for name, amount, d in items]
    return ("Understood. Let me read back your promise" + ("s" if len(items) > 1 else "") + ": " + "; ".join(parts) + ". "
            + _confirm_question(spec))


def run():
    spec = _spec()
    workdays, holidays = _calendar(spec)
    now = _today(spec)
    if now is None:
        vars["date_facts"] = "The current date is unknown. Ask nothing about dates you cannot check; say you cannot confirm dates."
        vars["account_facts"] = vars.get("account_facts") or "Account facts are not available."
        vars["facts_state"] = "no_date"
        return
    today = now.date()
    acc = spec.get("account") or dict()
    bands = acc.get("bands") or []
    lines = []
    lines.append("Now: " + _label(today) + " " + now.strftime("%H:%M") + ". Today is " + ("a business day." if _is_business(today, workdays, holidays) else "NOT a business day."))
    tomorrow = today + datetime.timedelta(days=1)
    lines.append("Tomorrow: " + _label(tomorrow) + ", " + ("a business day." if _is_business(tomorrow, workdays, holidays) else "NOT a business day."))
    nb = _next_business(today, workdays, holidays)
    if nb:
        lines.append("Next business day after today: " + _label(nb) + ".")
    lb = _last_business_of_week(today, workdays, holidays)
    if lb:
        lines.append("Last business day of the current calendar week (Monday to Sunday): " + _label(lb) + ". Today " + ("IS" if lb == today else "is NOT") + " that day.")
    lbn = _last_business_of_week(today + datetime.timedelta(days=7), workdays, holidays)
    if lbn:
        lines.append("Last business day of the following calendar week: " + _label(lbn) + ".")
    week_start = today - datetime.timedelta(days=today.weekday())
    this_week = [week_start + datetime.timedelta(days=i) for i in range(7)]
    next_week = [d + datetime.timedelta(days=7) for d in this_week]
    lines.append("Weekdays of the current calendar week: " + "; ".join(WEEKDAYS[d.weekday()] + " " + d.isoformat() for d in this_week) + ".")
    lines.append("Weekdays of the following calendar week: " + "; ".join(WEEKDAYS[d.weekday()] + " " + d.isoformat() for d in next_week) + ".")
    band_lines = []
    far = today + datetime.timedelta(days=21)
    for band in bands:
        dl = _deadline(band.get("deadline"), today, workdays, holidays)
        band["_deadline"] = dl
        if dl and dl > far:
            far = dl
        band_lines.append("Band " + str(band.get("name")) + " (" + str(acc.get("segment_field") or "segment") + " " + str(band.get("min")) + " to " + str(band.get("max")) + "): deadline " + (_label(dl) if dl else "see policy") + ", persuasion attempts " + str(band.get("persuasion_attempts")) + ".")
    if band_lines:
        lines.append("Deadlines computed from today: " + " ".join(band_lines))
    products = _parse_products(spec)
    floors = acc.get("floor_field_by_type") or dict()
    names = acc.get("spoken_name_by_type") or dict()
    seg = acc.get("segment_field") or "days_late"
    amount_field = acc.get("amount_field") or "past_due"
    id_field = acc.get("id_field") or "product_id"
    type_field = acc.get("type_field") or "type"
    recorded = _recorded([str(p.get(id_field)) for p in products])
    rows = []
    done_rows = []
    owed = dict()
    owed_amount = dict()
    product_deadlines = []
    plans = []
    for index, p in enumerate(products):
        kind = str(p.get(type_field) or "")
        seg_value = _num(p.get(seg))
        band = None
        for b in bands:
            lo, hi = _num(b.get("min")), _num(b.get("max"))
            if seg_value is not None and (lo is None or seg_value >= lo) and (hi is None or seg_value <= hi):
                band = b
                break
        floor_field, floor = _floor_of(p, _for_type(floors, kind), amount_field)
        dl = band.get("_deadline") if band else None
        product_deadlines.append(dl)
        owed[str(p.get(id_field))] = " (amount owed now " + _money(p.get(amount_field)) + "; deadline " + (_label(dl) if dl else "see policy") + ")"
        owed_amount[str(p.get(id_field))] = _money(p.get(amount_field))
        text = str(index + 1) + ". " + id_field + " " + str(p.get(id_field)) + ": " + _spoken(_for_type(names, kind), p)
        # A product at STOP is shown without its floor, plan and raw record: seen live, the model offered the floor it saw.
        done_rows.append(text + ": DONE. Every proposal allowed for it was made and refused: propose no amount and no date for it."
                         " Apply the policy for a product without a promise." + _already(recorded.get(str(p.get(id_field)))))
        text += "; amount owed now (" + amount_field + ") " + _money(p.get(amount_field))
        text += "; " + seg + " " + str(p.get(seg))
        if band:
            text += "; band " + str(band.get("name")) + "; deadline " + (_label(dl) if dl else "see policy") + "; persuasion attempts " + str(band.get("persuasion_attempts"))
        if floor is not None:
            text += "; floor (" + str(floor_field) + ") " + _money(floor)
        plan = band.get("attempt_plan") if band else None
        steps = []
        if isinstance(plan, list) and plan:
            tokens = {"amount": _money(p.get(amount_field)), "floor": _money(floor) if floor is not None else "the floor",
                      "deadline": _label(dl) if dl else "the deadline", "next_business_day": _label(nb) if nb else "the next business day",
                      "last_business_day_this_week": _label(lb) if lb else "the last business day of this week",
                      "last_business_day_next_week": _label(lbn) if lbn else "the last business day of next week"}
            for step in plan:
                step = str(step)
                for k, v in tokens.items():
                    step = step.replace("<" + k + ">", v)
                # The spec often numbers its own steps; the chain below numbers them again.
                steps.append(re.sub(r"^\s*(attempt|step)\s*\d+\s*[:.)-]\s*", "", step, flags=re.I))
            chain = ["after the first ask is refused: attempt 1: " + steps[0]]
            for i in range(1, len(steps)):
                chain.append("after attempt " + str(i) + " is refused: attempt " + str(i + 1) + ": " + steps[i])
            chain.append("after attempt " + str(len(steps)) + " is refused: STOP, no more payment proposals for " + str(p.get(id_field))
                         + " (it gets " + str(len(steps)) + (" proposal" if len(steps) == 1 else " proposals") + " after the first ask, even if another product gets more); apply the policy for a product without a promise")
            text += "; PERSUASION PLAN, the complete list of proposals for this product, one step per refusal or non-answer, nothing else in between: " + " | ".join(chain)
        text += ". Raw: " + json.dumps(p, sort_keys=True)
        rows.append(text)
        spoken = _spoken(_for_type(names, kind), p)
        try:
            allowed = int(band.get("persuasion_attempts")) if band else None
        except Exception:
            allowed = None
        plans.append((str(p.get(id_field)), spoken, steps, allowed, (_tokens(spoken) | _tokens(kind.replace("_", " ")) | _tokens(p.get(id_field))) - NAME_STOP,
                      _money(floor) if floor is not None else ""))
    deadlines = []
    for index, p in enumerate(products):
        if index < len(product_deadlines) and product_deadlines[index]:
            deadlines.append((str(p.get(id_field)), product_deadlines[index]))
    if not deadlines:
        deadlines = [("band " + str(b.get("name")), b.get("_deadline")) for b in bands if b.get("_deadline")]
    vars["named_day_facts"] = vars.get("named_day_facts") or "No exact day named yet."
    day_words = str(vars.get("named_day_words") or "").strip()
    given = day_words.strip(" .'\"").lower() not in ("", "none", "n/a", "null", "no")
    try:
        resolved = _resolve_day(day_words, today) if given else []
    except Exception:
        resolved = []
    # Words that name no day ('then', 'that day', 'yes'), seen extracted at confidence 0.95, are no day of the customer's
    # own: counted as one, they hid the next proposal. A vague period ('next month', 'when my salary comes') still is.
    day_named = bool(resolved) or (given and bool(_tokens(day_words) & VAGUE_DAY))
    named_date = resolved[0].isoformat() if len(resolved) == 1 else None
    count = len(rows)
    counts, changed, dated_now, question, accepted_now = _count_refusals(plans, day_named, named_date, today.isoformat(), recorded)
    first_closed = str(vars.get("first_ask_closed") or "") == "yes"
    # "I can't pay today" answers the first ask: today is not a day of the customer's own that is checked first.
    day_offered = day_named and named_date != today.isoformat()
    own = json.loads(vars.get("own_offer_products") or "[]")
    agreed = json.loads(vars.get("agreed_products") or "{}")
    # A finished product's deadline is no date to work with any more. Seen live: the band line and the calendar still named
    # it after its last proposal, and the model offered that product its floor on that date.
    finished = set(pl[0] for pl in plans if len(plans) > 1 and int(counts.get(pl[0]) or 0) > _total(pl))
    open_deadlines = [(name, dl) for name, dl in deadlines if name not in finished]
    if finished:
        lines = [l for l in lines if not l.startswith("Deadlines computed from today")]
    days = []
    d = today
    while d <= far + datetime.timedelta(days=7):
        days.append(_day_line(d, today, workdays, holidays, open_deadlines))
        d = d + datetime.timedelta(days=1)
    lines.append("Calendar, one line per day from today. When the customer names a day, find its line and apply the policy to what the line says:\n" + "\n".join(days))
    vars["date_facts"] = "\n".join(lines)
    _named_day(today, workdays, holidays, open_deadlines)
    # Per product the customer gave a day or an amount for: what the read-back says. Only a day the policy accepts as it
    # is (not past, a business day, on or before the product's deadline) is read back; any other day is settled first.
    details = dict()
    settled = []
    try:
        days_of = json.loads(str(vars.get("own_offer_days") or "{}"))
        days_of = days_of if isinstance(days_of, dict) else dict()
    except Exception:
        days_of = dict()
    for pid, label, _s, _a, _t, _f in plans:
        iso = str(days_of.get(pid) or "")
        try:
            day = datetime.date.fromisoformat(iso[:10]) if iso else None
        except Exception:
            day = None
        text = "the amount owed now, " + owed_amount.get(pid, "the amount owed") + ", unless the customer named another amount"
        if pid in agreed:
            # An accepted proposal is read back as proposed, with the day the customer gave instead when they gave one.
            step = int(agreed.get(pid) or 0)
            text = ("the amount" + ("" if iso else " and the day") + " of the last proposal the customer said yes to for it, normally attempt "
                    + str(step) + ": " + (_s[step - 1] if _s and 0 < step <= len(_s) else "persuasion attempt " + str(step) + " as the policy says")
                    + "; if the customer accepted the floor or named an amount of their own instead, that amount, checked under the amount rules")
        accepted = True
        if day:
            line = _day_line(day, today, workdays, holidays, open_deadlines)
            dl = dict(open_deadlines).get(pid)
            accepted = day >= today and _is_business(day, workdays, holidays) and (dl is None or day <= dl)
            if accepted:
                text = "the day the customer gave, " + _label(day) + " (calendar: " + line + "), and " + text
            else:
                text = ("the day the customer gave, " + _label(day) + ", is not accepted as it is (calendar: " + line
                        + "); the read-back uses the day the date rules give for it, and " + text)
        if ((pid in own or pid in agreed) and accepted) or "create_promise" in (recorded.get(pid) or []):
            settled.append(pid)
        details[pid + " " + label] = text
    # One product keeps the flow that passes today: the model counts its own plan.
    vars["plan_state"] = _plan_state(plans, counts, changed, own, details, recorded, day_offered, dated_now, question, first_closed, agreed, accepted_now) if len(plans) > 1 else "One product: follow its PERSUASION PLAN and count the proposals yourself."
    done, wrap, step = _wrap_up(plans, counts, settled, owed, details, recorded, agreed) if len(plans) > 1 else (False, "", "")
    prev_done = str(vars.get("negotiation_done") or "")
    if _amount_named(vars.get("named_amount_words")):
        vars["amount_named"] = "yes"
    vars["named_amount_words"] = "none"
    try:
        said = json.loads(str(vars.get("readback_said") or "{}"))
        said = said if isinstance(said, dict) else dict()
    except Exception:
        said = dict()
    say = ""
    if done:
        ids, items = [], []
        for pid, label, _s, _a, _t, _f in plans:
            if int(counts.get(pid) or 0) == 0 and pid in settled and "create_promise" not in (recorded.get(pid) or []):
                try:
                    day = datetime.date.fromisoformat(str(days_of.get(pid) or "")[:10])
                except Exception:
                    day = None
                ids.append((pid, label))
                items.append((label, owed_amount.get(pid, ""), day))
        key = dict((pid, str(days_of.get(pid) or "")[:10]) for pid, _ in ids)
        names = ", ".join(pid + " " + label for pid, label in ids)
        # The fixed line reads the amount owed; an accepted proposal (a floor, another day) is read back by the model.
        waiting = [pid for pid in agreed if pid in settled and "create_promise" not in (recorded.get(pid) or [])]
        if ids and not waiting and all(day and amount for _, amount, day in items):
            # Seen live: on the turn of the last refusal the model kept the pattern of its earlier proposals and made one more
            # for a finished product, whatever the step said. A fixed line has no pattern to follow. Only once per call, only
            # on a plain refusal turn, and never after the customer named an amount of their own (the line reads the amount owed).
            if not said and prev_done != "yes" and changed and not day_named and vars.get("amount_named") != "yes":
                say = _readback_line(spec, items)
            new_step = ""
            if say:
                said = key
                new_step = ("NEXT STEP: the read-back for " + names + " has just been said, word for word: \"" + say + "\" After a clear"
                            " yes call create_promise for each of them, then do the remaining closing steps. If the customer changes the"
                            " day or the amount, settle it under the date and amount rules and read the new one back.")
            elif said and said == key:
                new_step = ("NEXT STEP: the read-back for " + names + " was already said and the customer was asked to confirm it. If"
                            " they said a clear yes, call create_promise for each of them now, then do the remaining closing steps; do"
                            " not read it back again. If they changed the day or the amount, settle it under the date and amount rules"
                            " and read the new one back.")
            if new_step and wrap.endswith(step):
                wrap = wrap[:len(wrap) - len(step)] + new_step
                step = new_step
    vars["readback_said"] = json.dumps(said, sort_keys=True)
    vars["wrap_up_mode"] = "say" if say else "llm"
    vars["wrap_up_say"] = say or "Thank you."
    vars["negotiation_done"] = "yes" if done else "no"
    vars["wrap_up_facts"] = wrap or "Not in the closing phase."
    vars["wrap_up_step"] = step or "Not in the closing phase."
    for index, pl in enumerate(plans):
        if pl[0] in finished:
            rows[index] = done_rows[index]
    known = [(name, dl) for name, dl in deadlines if not name.startswith("band ") and name not in finished]
    if len(known) > 1 and len(set(dl for _, dl in known)) > 1:
        # One date named for several products is the multi-product case that needs the most date arithmetic.
        first = min(dl for _, dl in known)
        binding = [name for name, dl in known if dl == first]
        rows.append("Deadlines differ: the earliest is " + _label(first) + " (" + ", ".join(binding) + "). One date for all products"
                    " is on or before every product's deadline only if it is on or before " + first.isoformat() + "; "
                    + "; ".join(name + " deadline " + dl.isoformat() for name, dl in known) + ".")
    if rows:
        vars["account_facts"] = "Late products, in the order the bank returned them:\n" + "\n".join(rows)
        vars["product_count"] = str(count)
        vars["facts_state"] = "ready"
    else:
        vars["account_facts"] = "The product list could not be read by code. Use the get_account result in the conversation history."
        vars["facts_state"] = "no_products"


try:
    run()
except Exception as exc:
    vars["date_facts"] = vars.get("date_facts") or "Date facts are unavailable."
    vars["account_facts"] = vars.get("account_facts") or "Account facts are unavailable; use the get_account result in the conversation history."
    vars["facts_state"] = "error"
