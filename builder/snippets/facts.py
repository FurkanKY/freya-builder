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
    raw = str(vars.get(spec.get("now_variable") or "now") or "").strip()
    try:
        return datetime.datetime.fromisoformat(raw[:16])
    except Exception:
        pass
    try:
        return datetime.datetime.fromisoformat(raw[:10])
    except Exception:
        return None


def _calendar(spec):
    cal = spec.get("calendar") or dict()
    names = cal.get("business_weekdays") or WEEKDAYS[:5]
    workdays = set(WEEKDAYS.index(n) for n in names if n in WEEKDAYS)
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
    if kind == "end_of_month":
        first = (today.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        return first - datetime.timedelta(days=1)
    return None


def _label(d):
    return d.isoformat() + " (" + WEEKDAYS[d.weekday()] + ", " + str(d.day) + " " + d.strftime("%B") + " " + str(d.year) + ")"


def _parse_products(spec):
    acc = spec.get("account") or dict()
    field = acc.get("list_field") or "products"
    candidates = [vars.get("account_products"), vars.get("get_account_response.data." + field)]
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
    # Flattened keys such as get_account_response.data.products.0.past_due
    rows = dict()
    pattern = re.compile(r"(?:account_products|get_account_response\.data\." + re.escape(field) + r")[.\[](\d+)\]?\.(\w+)$")
    for key in list(vars.keys()):
        m = pattern.search(str(key))
        if m:
            rows.setdefault(int(m.group(1)), dict())[m.group(2)] = vars.get(key)
    return [rows[i] for i in sorted(rows)]


def _num(value):
    try:
        return float(value)
    except Exception:
        return None


def _money(value):
    v = _num(value)
    if v is None:
        return str(value)
    return ("%.2f" % v).rstrip("0").rstrip(".") if v != int(v) else str(int(v))


def _spoken(template, product):
    out = str(template or product.get("type") or "product")
    for k, v in product.items():
        out = out.replace("<" + str(k) + ">", str(v))
    return out


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
    nb = _next_business(today, workdays, holidays)
    if nb:
        lines.append("Next business day after today: " + _label(nb) + ".")
    lb = _last_business_of_week(today, workdays, holidays)
    if lb:
        lines.append("Last business day of the current calendar week (Monday to Sunday): " + _label(lb) + ".")
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
    rows = []
    product_deadlines = []
    for index, p in enumerate(products):
        kind = str(p.get(type_field) or "")
        seg_value = _num(p.get(seg))
        band = None
        for b in bands:
            lo, hi = _num(b.get("min")), _num(b.get("max"))
            if seg_value is not None and (lo is None or seg_value >= lo) and (hi is None or seg_value <= hi):
                band = b
                break
        floor_field = floors.get(kind)
        floor = p.get(floor_field) if floor_field else None
        dl = band.get("_deadline") if band else None
        product_deadlines.append(dl)
        text = str(index + 1) + ". " + id_field + " " + str(p.get(id_field)) + ": " + _spoken(names.get(kind), p)
        text += "; amount owed now (" + amount_field + ") " + _money(p.get(amount_field))
        text += "; " + seg + " " + str(p.get(seg))
        if band:
            text += "; band " + str(band.get("name")) + "; deadline " + (_label(dl) if dl else "see policy") + "; persuasion attempts " + str(band.get("persuasion_attempts"))
        if floor is not None:
            text += "; floor (" + str(floor_field) + ") " + _money(floor)
        plan = band.get("attempt_plan") if band else None
        if isinstance(plan, list) and plan:
            tokens = {"amount": _money(p.get(amount_field)), "floor": _money(floor) if floor is not None else "the floor",
                      "deadline": _label(dl) if dl else "the deadline", "next_business_day": _label(nb) if nb else "the next business day",
                      "last_business_day_this_week": _label(lb) if lb else "the last business day of this week",
                      "last_business_day_next_week": _label(lbn) if lbn else "the last business day of next week"}
            steps = []
            for step in plan:
                step = str(step)
                for k, v in tokens.items():
                    step = step.replace("<" + k + ">", v)
                steps.append(step)
            text += "; PERSUASION PLAN, the complete list of proposals for this product after the first ask, one step per refusal or non-answer, nothing else in between: " + " | ".join(steps)
        text += ". Raw: " + json.dumps(p, sort_keys=True)
        rows.append(text)
    deadlines = []
    for index, p in enumerate(products):
        if index < len(product_deadlines) and product_deadlines[index]:
            deadlines.append((str(p.get(id_field)), product_deadlines[index]))
    if not deadlines:
        deadlines = [("band " + str(b.get("name")), b.get("_deadline")) for b in bands if b.get("_deadline")]
    days = []
    d = today
    while d <= far + datetime.timedelta(days=7):
        text = d.isoformat() + " " + WEEKDAYS[d.weekday()]
        if _is_business(d, workdays, holidays):
            text += ": business day"
        else:
            text += ": HOLIDAY (" + holidays[d.isoformat()] + "), NOT a business day" if d.isoformat() in holidays else ": weekend, NOT a business day"
            prv = _previous_business(d, workdays, holidays)
            if prv:
                text += "; previous business day " + prv.isoformat() + " " + WEEKDAYS[prv.weekday()]
            nxt = _next_business(d, workdays, holidays)
            if nxt:
                text += "; next business day " + nxt.isoformat() + " " + WEEKDAYS[nxt.weekday()]
        inside = [name for name, dl in deadlines if d <= dl]
        after = [name for name, dl in deadlines if d > dl]
        if inside:
            text += "; on or before the deadline of " + ", ".join(inside)
        if after:
            text += "; AFTER the deadline of " + ", ".join(after)
        days.append(text)
        d = d + datetime.timedelta(days=1)
    lines.append("Calendar, one line per day from today. When the customer names a day, find its line and apply the policy to what the line says:\n" + "\n".join(days))
    vars["date_facts"] = "\n".join(lines)
    if rows:
        vars["account_facts"] = "Late products, in the order the bank returned them:\n" + "\n".join(rows)
        vars["product_count"] = str(len(rows))
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
