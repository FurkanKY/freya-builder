# holdout1 — rule map (verifiers only; not part of the material)

Material: `tests/fixtures/holdout1/01-mail-thread.md` (MAIL), `02-policy-extract.md` (COL), `03-memo.md` (MEMO), `04-code-list.md` (CL-7).
The four files together must have exactly the meaning of Brief A + Brief B. MEMO amends COL; where they differ MEMO wins (stated in MAIL 9 Oct, MAIL 8 Oct, COL header, MEMO header). The MEMO has **no date gate**: it is "effective immediately … to every call the assistant makes, whatever the date of the call", so the A + B meaning holds for any `now` a case or the harness picks (an earlier version was gated on 2026-10-12, which would have made the unamended extract govern calls before that day). Chronology of the pack: Ingrid's kick-off 7 Oct → MEMO dated 8 Oct and CL-7 version 7 dated 8 Oct → Jonas sends the pack 8 Oct 17:20 → Q&A mail 9 Oct. MAIL 9 Oct states that its numbered items 1–8 are binding in the same way as the three attachments.

Verbatim sentences the agent must say (kept word for word, in quotes): "Am I speaking with {title} {last_name}?" (COL-2.2), "I am sorry for your loss." (COL-3.5), "Can you make this payment today?" (COL-6.5), "Do you confirm?" (COL-7.1), "You will receive a text message confirming this promise." (MEMO 8 → COL-7.5), product wording "credit card ending 4821" / "personal loan" / "car loan" (COL-4.1 table), banned question "how much can you pay?" (COL-6.1, MAIL item 7).

## Brief A

| A rule | Content | Where |
|---|---|---|
| §1 | scope: 1–45 days late | COL-1.1 (extended to 1–3 products, = B1) |
| §2 | call variables, customer_id on every call, title + last name, `now` is the clock | MAIL 9 Oct item 1 (table) |
| 1 | opening sentence; no "collections"/"debt"/"payment"/product before verification; applies to relatives | COL-2.1 |
| 2 | "Am I speaking with {title} {last_name}?" | COL-2.2 |
| 3 | what counts as confirmation; ask once more; unclear → not_reached/unclear; answer a question first, the following ask is the second | COL-2.2 (a)–(d); CL-7 table row `unclear` |
| 4 | robot/AI question → Freya Bank's digital assistant, continue | MAIL 9 Oct item 4 (referenced by COL-2.2(d), COL-9.6) |
| 5 | someone else: say nothing beyond the opening, ask when reachable | COL-3.1 |
| 6 | callback today / next business day, 10:00–19:00 incl., date+time later than `now` (today: time later than call time; next business day: any time in the window — so PUB-02's tomorrow 11:00 on an 11:00 call is valid); schedule_callback; not_reached/callback | COL-3.2 as replaced by MEMO 4 |
| 7 | outside window: ask once more; still outside → no booking; not_reached/no_callback | COL-3.3 |
| 8 | wrong number → not_reached/wrong_number | COL-3.4; CL-7 |
| 9 | deceased: "I am sorry for your loss.", ask nothing else, not_reached/deceased | COL-3.5; CL-7 |
| 10 | relative never answers security questions, told nothing, even if offering to pay | COL-3.1 last sentence |
| 11 | two questions in order DOB then phone_last4; verify_identity per answer; YYYY-MM-DD; unreadable rejected; numbers = day, month, year | COL-2.3 |
| 12 | wrong answer may be re-asked; three wrong in total end the check | COL-2.4 as replaced by MEMO 2 |
| 13 | hint day_month_swapped → month as a word; retry not counted | COL-2.6 inserted by MEMO 3 |
| 14 | after limit: no debt stated, app or branch, not_verified/failed | COL-2.4 as replaced by MEMO 2; CL-7 |
| 15 | refusal: explain once; "what is this about" = refusal; second → not_verified/declined | COL-2.5; CL-7 |
| 16 | get_account after both pass | COL-2.7 |
| 17 | collections team, late payment; product in words; past_due and days_late | COL-4.1 + table |
| holidays | Mon–Fri except 2026-10-26, 11-11, 11-26, 12-25, 2027-01-01 | COL-1.2 (four dates) + MEMO 1 (adds 2026-11-26) |
| 18 | bands: 1–7 early → 12th business day, 1 attempt; 8–45 late → 7th business day, 2 attempts | COL-5.1 table (early = 10th) replaced by MEMO 5 (early = 12th) |
| 19 | promise date today or later, business day, ≤ deadline | COL-5.2 |
| 20 | weekend/holiday not after deadline → next business day; after → rule 23 | COL-5.3 |
| 21 | vague period → ask once; none → propose the deadline | COL-5.4 |
| 22 | next/this <weekday> convention | MAIL 9 Oct item 2 (COL-1.3 defines weeks as Mon–Sun) |
| 23 | date after deadline → latest recordable is the deadline, offer it; refusal = flat refusal | COL-5.5 |
| 24 | full amount first; never "how much can you pay?"; agent proposes every amount | COL-6.1; MAIL item 7 |
| 25 | floor: minimum_payment / instalment_amount | COL-6.2 table |
| 26 | too much → floor once, rest stays overdue; refuse → flat refusal; attempt 2 may name floor again on the deadline | COL-6.3 |
| 27 | own amount floor..full accepted; below → cannot record, floor once; refuse → flat refusal | COL-6.4 |
| 28 | "Can you make this payment today?" | COL-6.5 (single product); multi-product form = B4 |
| 29 | a proposed date or amount is never a refusal, at any point of the call | COL-6.6 first sentence (general, not tied to the first question) |
| 30 | flat refusal / non-answer uses an attempt; no-without-date-or-amount = flat refusal; attempt 1 amount; attempt 1 date; attempt 2 late only floor on deadline | COL-6.6 + attempt table |
| 31 | attempts exhausted: stop, no repeat of a refused offer, no_promise/refused | COL-6.7; CL-7 row `refused` |
| 32 | hardship: sympathy, no attempt, offer support; accept → transfer support / transferred/support; decline → no_promise/hardship; precedence over 30 and 41; own date/amount still recorded | COL-6.8 as replaced by MEMO 6; CL-7 |
| 33 | no discount, waiver, plan or other term | COL-6.9 as replaced by MEMO 7 |
| 34 | read back product/amount/date, "Do you confirm?", create_promise after a clear yes | COL-7.1 |
| 35 | change at read-back → re-check, read back again | COL-7.2 |
| 36 | one promise per product; no change/cancel in call; mobile app | COL-7.3 |
| 37 | "recorded" only after ok:true; retry once; second failure → could not record, no_promise/service_error | COL-7.4 (single-product branch) |
| 38 | text-message sentence | COL-7.5 as replaced by MEMO 8 |
| 39 | already paid: one business day to appear, no promise, close paid | COL-9.1; CL-7 |
| 40 | dispute incl. closed/paid off in the past; no argument, no promise, no_promise/dispute; rule 39 only for this past-due amount | COL-9.2; COL-9.1 last sentence; CL-7 |
| 41 | plan / lower instalments → no plan described; transfer restructuring; transferred/restructuring | COL-9.3; CL-7 D |
| 42 | human: ask once if you can help; insist → transfer general; transferred/human | COL-9.4; CL-7 D |
| 43 | scam → verify via customer service number, continue | MAIL 9 Oct item 5 |
| 44 | unknown → say you do not have that information; invent nothing | MAIL 9 Oct item 6 |
| 45 | twice "don't want to talk": no_promise/refused after, not_verified/declined before; rule 42 before and after | COL-9.5; COL-9.4 last sentence; CL-7 rows |
| 46 | exactly one close_call, last tool call; outcome/reason table; transfer after promise → transferred | CL-7 A.1–A.2, table, C.1; MAIL item 8 |
| 46 (A never uses add_note) | single-product calls write no note | CL-7 B.2 |
| 47 | thank and say goodbye before close_call | CL-7 A.3; MAIL item 8 |

## Brief B

| B rule | Content | Where |
|---|---|---|
| 1 | 1–3 products, each own past_due/days_late/floor | COL-8.1; COL-1.1 |
| 2 | state every late product, one sentence each, before asking anything | COL-4.1 |
| 3 | band and deadline per product; may differ | COL-5.1 ("by its own days_late"); COL-8.1 |
| 4 | first ask all today; else one by one in get_account order; no second "today"; each product starts at attempt 1 | COL-6.5 (multi form); COL-8.2 |
| 5 | attempts counted per product | COL-8.2 |
| 6 | one date for all; after a product's deadline → that product on its deadline, said in read-back; others keep the date | COL-8.3 |
| 7 | read all back together, one confirmation, then create_promise per product | COL-7.1 |
| 8 | add_note per product without promise: refused/hardship/dispute/paid/service_error; also when none promised | CL-7 B.1, B.3 + table |
| 9 | dispute / paid on one product does not end the call | COL-8.4; COL-9.1, COL-9.2 (multi branches) |
| 10 | restructuring still transfers; recorded promises stay; agreed-but-unrecorded not recorded; no notes on any transfer | COL-8.5; CL-7 B.4, C.1 |
| 11 | create_promise fails twice → keep recorded, note service_error | COL-7.4 (multi branch); CL-7 row `service_error` |
| closing | all paid → paid; else no_promise with reason of first non-paid note in get_account order; promise wins if ≥1 recorded except transfer | CL-7 C.1–C.3 |

## Memo amendments (extract value → memo value → net)

| MEMO item | Clause | Extract (old) | Memo (new) | Net = |
|---|---|---|---|---|
| 1 | COL-1.2 | four closure days, no 2026-11-26 | adds 2026-11-26 | A holidays (five dates) |
| 2 | COL-2.4 | two wrong answers end the check | three wrong answers in total | A12, A14 |
| 3 | COL-2.6 | reserved (empty) | day_month_swapped handling | A13 |
| 4 | COL-3.2 | callback 09:00–18:00 | 10:00–19:00, both included, date+time later than `now` | A6 |
| 5 | COL-5.1 | early band latest date = tenth business day after today | twelfth business day after today (late band unchanged: seventh, two attempts) | A18 |
| 6 | COL-6.8 | hardship: no attempt, product ends `hardship` (no support offer) | sympathy sentence, no attempt, offer support once, transfer `support` / else `hardship`, precedence over COL-6.6 and COL-9.3, own date/amount still recorded | A32 |
| 7 | COL-6.9 | assistant may offer a two-payment split | no discount, waiver, instalment plan or other term | A33 |
| 8 | COL-7.5 | "written confirmation will be posted" | exact sentence "You will receive a text message confirming this promise." | A38 |

## Merge decisions (A + B into one body of material)

- Notes: A never uses add_note; B notes every product without a promise. Net rule in CL-7 B.2/B.3: notes only when get_account returned two or more products. This is what the 13 public cases require (A cases: `notes: []`). B.2 deliberately resolves an ambiguity the public briefs leave open (B rule 8 read literally would note a single product too). **Hard constraint for case authors: never write a holdout1 case that expects a note on a single-product call.**
- Hardship with several products (not spelled out in B beyond note reason `hardship`): MEMO 6 says every product that has *not yet ended* (no promise recorded, no note written) is noted `hardship`; a product that already ended (e.g. p1 noted `refused` before the job-loss remark on p2) keeps its own note, and the close reason follows CL-7 C.3 (so p1 `refused`, p2/p3 `hardship` → `no_promise` / `refused`). CL-7 B row `hardship` says the same. "Offers, once" matches PUB-05's check "support team offered once".
- A4 (robot question): MAIL item 4 says "digital assistant, carries on, no hand-off" — it does not forbid an apology, because Brief A does not.
- A37: COL-7.4 names the `create_promise` call explicitly ("If the `create_promise` call fails, it is repeated once"), so "the call" is not confused with the phone call.
- COL-7.4, COL-9.1, COL-9.2, COL-6.7 each carry a single-product branch (A: close) and a several-product branch (B: note and continue).
- COL-1.3 (today not counted; weeks are Mon–Sun) and MAIL item 3 (worked example for 8 Oct → 19 Oct) only restate how A counts; they add no behaviour.

## Where each file carries rules that appear nowhere else

- MAIL only: A §2 variables, A4, A22, A43, A44. (MAIL 9 Oct declares items 1–8 binding like the attachments; COL-2.2(d) and COL-9.6 cross-reference items 4–6; items 1–2 are reached only through that declaration.)
- MEMO only (net values): A6 hours, A12/A14 limit, A13, A18 early deadline, A32, A33, A38, holiday 2026-11-26.
- CL-7 only: A46 close table and single-close rule, A47, "no note with one product", B8 note table, B closing precedence, B10 "no notes on transfer" (also COL-8.5).
- COL only: everything else.
