# Runs inside a Freya code node. The compiler prepends NOW_VARIABLE and LANGUAGE (string literals).
# Only json, re and datetime are used. Never raise; always write date_facts. No double braces anywhere (template markers).
import re
import datetime

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
# The call's language says dates in its own words; the agent copies them instead of translating weekday names itself.
OWN = dict(tr=(["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"],
               ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]))


def _clock(raw):
    """The call's local date and time as written: ISO (T or space, optional seconds, Z or offset, which is not applied),
    or day first DD.MM.YYYY / DD/MM/YYYY with an optional HH:MM."""
    raw = str(raw or "").strip()
    t = r"(?:[T ,]+(\d{1,2}):(\d{2}))?"
    for pattern, order in ((r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})" + t, "ymd"), (r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})" + t, "dmy")):
        m = re.search(pattern, raw)
        if m:
            parts = dict(zip(order, m.groups()[:3]))
            try:
                return datetime.datetime(int(parts["y"]), int(parts["m"]), int(parts["d"]), int(m.group(4) or 0), int(m.group(5) or 0))
            except Exception:
                return None
    return None


def _own():
    lang = str(LANGUAGE or "").strip().lower()
    return OWN.get(lang[:2]) or OWN.get("tr" if lang.startswith(("turk", "türk")) else "")


def _label(d):
    text = WEEKDAYS[d.weekday()] + ", " + str(d.day) + " " + MONTHS[d.month - 1] + " " + str(d.year)
    own = _own()
    if own:
        text = text + " = " + str(d.day) + " " + own[1][d.month - 1] + " " + str(d.year) + " " + own[0][d.weekday()]
    return d.isoformat() + " (" + text + ")"


def run():
    found = None
    for name in (NOW_VARIABLE, "now"):
        found = _clock(vars.get(name))
        if found is not None:
            break
    lines = []
    if found is None:
        # Only without a call date: the sandbox clock, said as such.
        found = datetime.datetime.now()
        lines.append("The call gave no date; these facts use the system clock.")
    today = found.date()
    lines.append("Now: " + _label(today) + " " + found.strftime("%H:%M") + ". A time named without a day is on this date.")
    lines.append("Tomorrow: " + _label(today + datetime.timedelta(days=1)) + ".")
    monday = today - datetime.timedelta(days=today.weekday())
    lines.append("Weeks run Monday to Sunday. This week: " + _label(monday) + " to " + _label(monday + datetime.timedelta(days=6)) + ".")
    for n in range(1, 7):
        start = monday + datetime.timedelta(days=7 * n)
        lines.append(("Next week" if n == 1 else "Week " + str(n) + " from now") + ": " + _label(start) + " to "
                     + _label(start + datetime.timedelta(days=6)) + ".")
    # A statement's cut-off is often weeks back and its due date weeks ahead: the weekday of a tool's date is looked up here.
    lines.append("Days (35 back to 45 ahead): " + "; ".join(_label(today + datetime.timedelta(days=k)) for k in range(-35, 46)) + ".")
    vars["date_facts"] = "\n".join(lines)


try:
    run()
except Exception:
    vars["date_facts"] = vars.get("date_facts") or "Date facts are unavailable."
