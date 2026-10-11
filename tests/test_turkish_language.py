import datetime
import json
from pathlib import Path
from builder.compile import compile_workflow
from builder.runtime import validate_workflow

ROOT = Path(__file__).resolve().parent.parent
API = json.loads((ROOT/"vendor/kit-v3/tools/openapi.json").read_text())
SPEC = json.loads((ROOT/"tests/fixtures/spec_sample.json").read_text())
BRIEFS = [{"path": "memo.md", "text": "brief"}]
TODAY = datetime.date(2026, 10, 14)  # a Wednesday
PRODUCTS = [{"product_id": "p1", "type": "credit_card", "card_last4": "1234", "past_due": 300.0, "days_late": 4, "minimum_payment": 90.0}]


def _spec(language):
    spec = json.loads(json.dumps(SPEC))
    spec["language"] = language
    return spec


def _code(spec, node):
    wf = compile_workflow(spec, API, BRIEFS)
    return wf["nodes"][node]["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]


def _scope(language="Turkish", now="2026-10-14T11:00"):
    scope = {"vars": {"now": now}}
    exec(compile(_code(_spec(language), "check_date"), "facts", "exec"), scope)
    return scope


def _run(language, variables):
    exec(compile(_code(_spec(language), "account_facts"), "facts", "exec"), {"vars": variables})
    return variables


def _days(scope, words):
    return [d.isoformat() for d in scope["_resolve_day"](words, TODAY)]


def test_a_turkish_spec_compiles_and_reads_its_language_in_any_spelling():
    assert validate_workflow(compile_workflow(_spec("Turkish"), API, BRIEFS), API) == []
    for language in ("Turkish", "turkish", "Türkçe", "TÜRKÇE", "tr-TR", "tr"):
        assert _scope(language)["_turkish"](), language
    for language in ("English", "en-GB", "", None):
        assert not _scope(language)["_turkish"](), language


def test_turkish_weekdays_with_their_endings():
    scope = _scope()
    for words, days in (("cuma", ["2026-10-16"]), ("cumaya", ["2026-10-16"]), ("Cuma günü", ["2026-10-16"]),
                        ("cumartesi günü", ["2026-10-17"]), ("pazartesiye", ["2026-10-19"]), ("PAZARTESİ", ["2026-10-19"]),
                        ("pazar", ["2026-10-18"]), ("pazara", ["2026-10-18"]), ("salıya", ["2026-10-20"]), ("SALI", ["2026-10-20"]),
                        ("perşembe günü", ["2026-10-15"]), ("carsamba", ["2026-10-14", "2026-10-21"]),
                        ("haftaya cuma", ["2026-10-23"]), ("gelecek hafta salı", ["2026-10-20"]), ("bu cuma", ["2026-10-16"]),
                        # As in English 'next Monday': this one or the one after, the agent asks.
                        ("önümüzdeki pazartesi", ["2026-10-19", "2026-10-26"])):
        assert _days(scope, words) == days, words


def test_turkish_relative_days():
    scope = _scope()
    for words, days in (("bugün", ["2026-10-14"]), ("yarın", ["2026-10-15"]), ("Yarın", ["2026-10-15"]),
                        ("öbür gün", ["2026-10-16"]), ("ertesi gün", ["2026-10-16"]), ("yarından sonra", ["2026-10-16"]),
                        ("haftaya bugün", ["2026-10-21"]), ("şimdi", ["2026-10-14"]),
                        ("gelecek ayın 5'i", ["2026-11-05"]), ("bu ayın 20'si", ["2026-10-20"])):
        assert _days(scope, words) == days, words
    # A period, not a day: no date, as English 'next week' or 'end of the month'.
    for words in ("haftaya", "gelecek hafta", "önümüzdeki hafta", "bu hafta", "hafta sonu", "ay sonu", "ayın sonu", "gelecek ay",
                  "önümüzdeki ay", "maaşım yatınca", "kasımda"):
        assert _days(scope, words) == [], words


def test_turkish_ordinal_and_numeric_days():
    scope = _scope()
    for words, days in (("15'inde", ["2026-10-15"]), ("15’inde", ["2026-10-15"]), ("15 Ekim", ["2026-10-15"]),
                        ("ekimin 15'i", ["2026-10-15"]), ("ayın 15'i", ["2026-10-15"]), ("on beşinde", ["2026-10-15"]),
                        ("ayın on beşi", ["2026-10-15"]), ("yirmi üçünde", ["2026-10-23"]), ("yirmi altısında", ["2026-10-26"]),
                        ("otuz birinde", ["2026-10-31"]), ("Ekim'in yirmi dokuzu", ["2026-10-29"]), ("3 Kasım", ["2026-11-03"]),
                        ("Kasım'ın üçü", ["2026-11-03"]), ("23.10.2026", ["2026-10-23"]), ("23/10", ["2026-10-23"]),
                        ("15 Mayıs", ["2027-05-15"]), ("1 Ocak", ["2027-01-01"]), ("Salı 26'sı", ["2026-10-26"])):
        assert _days(scope, words) == days, words
    # A pronoun is not 'on' (ten), and 'ikisi de' (both) is not the second.
    assert _days(scope, "onu cuma öderim") == ["2026-10-16"]
    assert _days(scope, "ikisini de cuma") == ["2026-10-16"]
    assert _days(scope, "10.30") == []


def test_turkish_number_words_and_lira_formats():
    scope = _scope()
    amount, num = scope["_tr_amount"], scope["_num"]
    for words, value in (("bin iki yüz elli", 1250), ("bin iki yüz elli lira", 1250), ("iki bin", 2000), ("yüz", 100),
                         ("beş yüz", 500), ("DÖRT YÜZ", 400), ("on bin", 10000), ("üç yüz bin", 300000), ("iki milyon", 2000000),
                         ("iki buçuk", 2.5), ("bin buçuk", 1500), ("iki buçuk milyon", 2500000), ("2 bin 500 lira", 2500),
                         ("1.250,50", 1250.5), ("1.250 TL", 1250), ("₺1.250", 1250), ("1250", 1250),
                         ("yüz lira elli kuruş", 100.5), ("elli kuruş", 0.5)):
        assert amount(words) == value, words
    assert amount("hiç") is None and amount("yarım") is None
    assert num("1.250 TL") == 1250 and num("₺1.250") == 1250 and num("1.250,50 TL") == 1250.5
    # Without a lira mark a dot is still a decimal point.
    assert num("1.250") == 1.25 and num("EUR 1.250") == 1.25 and num("1,234.50") == 1234.5


def test_turkish_amount_words_are_an_amount_of_the_customers_own():
    named = _scope()["_amount_named"]
    for words in ("iki yüz", "300", "yarısını", "asgari ödeme", "bir taksit"):
        assert named(words), words
    for words in ("borcun tamamı", "tamamını", "hepsini bir seferde", "Hepsini", "yok", "hayır", "none"):
        assert not named(words), words


def test_turkish_yes_and_no():
    scope = _scope()
    no_value, bare_no = scope["_no_value"], scope["_bare_no"]
    for words in ("evet", "Tamam", "olur", "onaylıyorum", "kabul ediyorum", "yok"):
        assert no_value(words), words
    for words in ("kabul etmiyorum", "hayır", "istemiyorum", "olmaz", "ödeyemem", "Hayır, ödeyemem", "tamam ama ödeyemem"):
        assert not no_value(words) and bare_no(words), words
    assert not bare_no("kredi kartı")


def test_turkish_clock_values():
    clock = _scope()["_clock"]
    for raw, value in (("11 Ekim 2026 20:15", datetime.datetime(2026, 10, 11, 20, 15)),
                       ("Pazar, 11 Ekim 2026, 20:15", datetime.datetime(2026, 10, 11, 20, 15)),
                       ("11 Şubat 2026", datetime.datetime(2026, 2, 11)), ("11 Ağustos 2026 09:30", datetime.datetime(2026, 8, 11, 9, 30)),
                       ("11.10.2026 20:15", datetime.datetime(2026, 10, 11, 20, 15))):
        assert clock(raw) == value, raw
    out = _run("Turkish", {"now": "21 Ekim 2026 09:00", "account_products": json.dumps(PRODUCTS)})
    assert out["date_facts"].startswith("Now: 2026-10-21 (Wednesday, 21 October 2026) 09:00.")


def test_turkish_day_words_are_checked_in_code_and_cleared():
    out = _run("Turkish", {"now": "2026-10-21T09:00", "account_products": json.dumps(PRODUCTS)})
    out = _run("Turkish", dict(out, named_day_words="Pazartesi 26'sı"))
    assert out["named_day_words"] == "none"
    assert "2026-10-26 Monday: HOLIDAY (bank holiday), NOT a business day" in out["named_day_facts"]
    out = _run("Turkish", dict(out, named_day_words="Kasımın yedisi"))
    assert "2026-11-07 Saturday: weekend, NOT a business day" in out["named_day_facts"]
    # A period leaves the last check in place.
    out = _run("Turkish", dict(out, named_day_words="maaşım yatınca"))
    assert out["named_day_words"] == "none" and "2026-11-07" in out["named_day_facts"]
    out = _run("Turkish", dict(out, named_day_words="Salı 26'sı"))
    assert "The customer said Tuesday, but that date is a Monday" in out["named_day_facts"]
    out = _run("Turkish", dict(out, named_day_words="haftaya cuma"))
    assert "2026-10-30 Friday: business day; AFTER the deadline of p1" in out["named_day_facts"]


def test_english_words_in_a_turkish_call_keep_their_dates():
    # The extraction may write the day in English: 'on' is then not the Turkish ten.
    english, turkish = _scope("English"), _scope()
    for words in ("on 15 October", "on Monday", "on the 15th", "the 15th", "Monday the 26th", "on Friday the 16th", "next Friday",
                  "Friday next week", "tomorrow", "the day after tomorrow", "today"):
        assert _days(turkish, words) == _days(english, words) != [], words


def test_english_results_are_unchanged():
    scope = _scope("English")
    for words, days in (("tomorrow", ["2026-10-15"]), ("the day after tomorrow", ["2026-10-16"]), ("Friday", ["2026-10-16"]),
                        ("next Friday", ["2026-10-16", "2026-10-23"]), ("Friday next week", ["2026-10-23"]),
                        ("Wednesday", ["2026-10-14", "2026-10-21"]), ("the twenty-sixth", ["2026-10-26"]),
                        ("twenty six October", ["2026-10-26"]), ("on 15 October", ["2026-10-15"]), ("one week", []), ("next week", [])):
        assert _days(scope, words) == days, words
    # An English agent reads no Turkish.
    assert scope["_day_words"]("haftaya cuma", TODAY) == "haftaya cuma"
    for words in ("cuma", "yarın", "15'inde", "haftaya cuma"):
        assert _days(scope, words) == [], words
    assert not scope["_bare_no"]("hayır") and scope["_bare_no"]("No, I won't pay that")
    assert scope["_amount_named"]("two hundred") and not scope["_amount_named"]("all of it")
    assert scope["_no_value"]("none") and not scope["_no_value"]("credit card")
    assert scope["_num"]("1.250") == 1.25 and scope["_num"]("510.00") == 510


def test_a_turkish_agent_gets_the_frame_sentences_and_the_honorific_in_turkish():
    # Seen in a Turkish rehearsal: the agent said "Go on." in English, and the opening said the record's "Mr" as is.
    for language in ("Turkish", "Türkçe", "tr-TR"):
        wf = compile_workflow(_spec(language), API, BRIEFS)
        assert '"Go on."' not in wf["system_prompt"] and "missed that" not in wf["system_prompt"], language
        assert '"Devam edin lütfen."' in wf["system_prompt"], language
        for title, said in (("Mr", "Bay"), ("Ms", "Bayan"), ("mrs.", "Bayan"), ("Dr", "Dr"), ("Bay", "Bay"), ("", "")):
            variables = {"title": title, "now": "2026-10-14T11:00"}
            exec(compile(_code(_spec(language), "prepare"), "prepare", "exec"), {"vars": variables})
            assert variables["title"] == said, (language, title)
    wf = compile_workflow(_spec("English"), API, BRIEFS)
    assert '"Go on."' in wf["system_prompt"]
    variables = {"title": "Mr", "now": "2026-10-14T11:00"}
    exec(compile(_code(_spec("English"), "prepare"), "prepare", "exec"), {"vars": variables})
    assert variables["title"] == "Mr"


def test_an_opening_without_a_question_is_followed_in_the_same_turn_by_the_checklist_question_naming_the_person():
    spec = _spec("Turkish")
    spec["opening_line"] = "Merhaba, ben Freya Bank'ın dijital asistanıyım. Bu görüşme kayıt altına alınmaktadır."
    spec["policy"]["before_verification"] = ("1) Açılışta opening_line birebir söylenir. 2) '{{first_name}} {{last_name}} ile mi"
                                             " görüşüyorum?' diye sorulur; yalnızca 'evet' veya 'benim' onaydır.")
    said = compile_workflow(spec, API, BRIEFS)["nodes"]["identify"]["on_enter"]["text"]
    assert said == spec["opening_line"] + " {{first_name}} {{last_name}} ile mi görüşüyorum?"
    # An opening that already asks, or a checklist question naming no call variable, leaves the opening as it is.
    spec["policy"]["before_verification"] = "1) Açılışı birebir söyle. 2) 'First name last_name ile mi görüşüyorum?' diye sor."
    assert compile_workflow(spec, API, BRIEFS)["nodes"]["identify"]["on_enter"]["text"] == (
        spec["opening_line"] + " {{first_name}} {{last_name}} ile mi görüşüyorum?")
    spec["policy"]["before_verification"] = "1) Açılış söylenir. 2) 'Kiminle görüşüyorum?' diye sorulur."
    assert compile_workflow(spec, API, BRIEFS)["nodes"]["identify"]["on_enter"]["text"] == spec["opening_line"]
    spec["opening_line"] = "Hi, this is Freya Bank. Am I speaking with {{first_name}}?"
    spec["policy"]["before_verification"] = "1) Ask '{{first_name}} {{last_name}}, is that you?'"
    assert compile_workflow(spec, API, BRIEFS)["nodes"]["identify"]["on_enter"]["text"] == spec["opening_line"]
