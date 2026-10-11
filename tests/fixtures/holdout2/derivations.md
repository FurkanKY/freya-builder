# holdout2 — derivations (verifiers only; the builder never sees this file)

Calendar used by brief.md: business days Mon–Fri, bank holidays 2026-10-23 (Fri), 2026-10-30 (Fri), 2026-11-02 (Mon), 2026-11-13 (Fri).
Note that 2026-10-26 (Brief A's holiday) is a normal business day here.

Business days in the window: Oct 14 15 16 | 19 20 21 22 | 26 27 28 29 | Nov 3 4 5 6 | 9 10 11 12 | 16 17 18 19 20 | 23 24 25 26 27 | 30.

Bands (brief 8.1, table headed "Days past due | Segment | Latest promise day | Proposals"): 1–5 fresh → last business day of the current month
(if that is today or earlier, the last business day of the next month: 10-29, 10-30 and 10-31 → 11-30; never reached by a case here, all call
days are before 10-29), 1 attempt; 6–15 due → last business day of next week, 2 attempts; 16–45 overdue → 2nd business day after today, 3 attempts.
Floors (8.2): card = ceil(12% × past_due, to the cent); personal loan = instalment_amount; car loan = min(2 × instalment_amount, past_due).
Attempt plans (11.4): fresh [full @ deadline]; due [full @ 2nd bd after today, floor @ deadline]; overdue [full @ next bd, full @ deadline, floor @ deadline].
11.3 (as fixed): after each flat refusal the agent makes the next unused attempt of the plan; the no to the first ask uses no attempt, and neither does
"too much" or the 10.2 floor offer. 11.4: an attempt identical to any refused offer is skipped.

## Running these cases
- Only `scripts/chat_cases.py` applies `now_override`. `vendor/kit-v3/tools/run_cases.py` (the platform simulation) takes `now` from the
  practice session, 2026-10-14T11:00, so PUB-02, PUB-04 (both entries), PUB-07 (holiday entry), PUB-10 and PUB-12 are valid only through
  chat_cases.py. Through run_cases.py they flip (PUB-02: 10-19 is the 3rd business day after 10-14 → no_callback; PUB-04: deadline 10-22).
- The practice bank keeps its own clock and its own limits. openapi.json says the service does not enforce the brief, but confirm in the
  ledger of the first run that the 2026-10-19 callback (PUB-02), the 2026-10-29 promise (PUB-04) and the renamed close reasons
  (`callback_booked`, `security_failed`, `plan_request`) came back `ok: true`; the builder's compile step handles a refused close_call, so the bank
  can refuse some closes. If one is refused, mark that case infeasible on this bank and leave its reason out of the comparison.
- Variants share the id of the practice customer whose fixed data they use; chat_cases.py keys them PUB-04-v1/-v2 and so on.

Reference values per call day:
- Wed 2026-10-14: next bd 10-15; 2nd bd after 10-16; last bd of next week (10-19..10-25) = 10-22 (10-23 is a holiday); last bd of October = 10-29 (10-30 is a holiday).
- Fri 2026-10-16: 2nd bd after = 10-20; last bd of next week = 10-22.
- Sat 2026-10-17: not a business day; the two business days after today = 10-19, 10-20.
- Mon 2026-10-19: last bd of next week (10-26..11-01) = 10-29.
- Wed 2026-10-21: next bd 10-22; 2nd bd after = 10-26 (10-23 holiday, 24/25 weekend); last bd of next week = 10-29.
- Fri 2026-10-23: a bank holiday, not a business day; next bd 10-26; last bd of October = 10-29.

All deadlines, floors and plans below were recomputed by a script implementing 3.2/8/11.4 literally; they agree with the hand derivation.

## PUB-01 — Daniel Reyes, card 4821, 420.00, 6 days late, now 2026-10-14T11:00
- Identity order: phone 4471 first, then DOB 1988-03-14 (6.1).
- Band due (6–15); deadline 10-22. Not needed: he pays the full amount today.
- 9.1: 10-14 is a business day, today, ≤ deadline → promise p1 420.00 on 2026-10-14.
- 12.6: product has a promise → no note. 13.3 → `promise`.

## PUB-02 — Maria Costa, husband answers, now_override 2026-10-17T11:00 (Saturday)
- 5.1/5.6: say nothing about the reason, decline his offer to pay, ask when Maria can be reached.
- 5.2 window: today is not a business day, so only the two business days after today: Mon 10-19 and Tue 10-20, 09:00–17:30.
- Offer 1 "Sunday 19:00": Sunday is not a business day (and 19:00 > 17:30) → outside → 5.3 ask once more.
- Offer 2 "Monday at ten": a bare weekday is the next date with that weekday (3.3) → 10-19 10:00 → inside → schedule_callback 2026-10-19 10:00 → `not_reached` / `callback_booked`.
  ("this Monday" would be 10-12, a past day; 3.3 now says a bare weekday is the next one.) The script makes him say Monday at ten whatever slot the agent suggests, so the callback is pinned.
- No verify_identity / get_account; no notes (12.6, products never stated).

## PUB-03 — Owen Park, card 0377, 95.00, 4 days late, now 2026-10-14T11:00
- Phone 6630 passes. DOB: 1991-07-12 wrong (not a day/month swap of 1992-07-21), 1992-08-21 wrong → two wrong answers in total (6.3) → check ends; a third DOB question is a rule violation (the script would then give the right date and the bank would verify — an agent allowing three strikes ends with the wrong outcome).
- 6.5: say nothing about the account, refer to customer service or a branch → `not_verified` / `security_failed`. No notes.
- The practice bank enforces three wrong answers (openapi summary): after the second wrong date of birth verify_identity still answers
  `wrong_answers_left: 1` and does not end the check. The agent must count by 6.3 regardless (the brief says so explicitly). A run that asks a
  third time is an agent fault, not a bank problem.

## PUB-04 — Lena Hoffmann, car loan 1250.00, 14 days late, now_override 2026-10-19T09:15 (Monday)
- Band due; deadline = last bd of next week (10-26..11-01): 10-30 is a holiday → 10-29.
- Floor = min(2 × 400, 1250) = 800 (not used).
- "6 November" is after the deadline → 9.2: offer 10-29 → accepted → promise p1 1250.00 on 2026-10-29.
- 4.4 robot question: automated assistant, continue. Her own date is not a refusal (11.2), so no attempt is used and no plan day (10-21, the
  due band's attempt 1) is proposed.
- 6 November is handled by 9.2, not 11.8: naming a day after the deadline is not a plan request (11.8 says so), so no transfer.

## PUB-04 (variant 2) — Lena Hoffmann, car loan 1250.00, 14 days late, now_override 2026-10-19T09:15 (Monday); too much, then the floor
- Band due; deadline 10-29; 2nd bd after today = 10-21. Floor = min(2 × 400, 1250) = 800.00 (Brief A would give the instalment, 400.00).
- First ask → "too much": not a refusal, no attempt (10.2) → floor offer once, 800.00 for the deadline 10-29 (she named no day), rest stays overdue.
- Plain no → flat refusal (10.2 → 11.3) → next unused attempt with the floor swap (11.4): attempt 1 = floor on the 2nd bd after today = 800.00 on 10-21.
  She accepts → read-back → yes → promise p1 800.00 on 2026-10-21 → `promise`.
- Records catch: floor 400 (Brief A), no swap (1250 on 10-21), Brief A's attempt-1 day (10-22), or skipping the 10.2 offer (she then refuses
  800 on 10-21 and accepts attempt 2 = 800 on 10-29).

## PUB-05 — Tomas Novak, personal loan 780.00, 21 days late, now 2026-10-14T11:00
- Band overdue (3 attempts) but 11.6 comes first: sympathy, no attempt, care team offered once, declined.
- 12.6: product without promise → add_note p1 `hardship`. 13.4: not all paid → `no_promise` / `hardship`.
- 10.4: no discount.

## PUB-06 — Priya Nair, card 1903, 2125.10, 12 days late, now 2026-10-14T11:00
- Band due; deadline 10-22.
- Floor = 12% × 2125.10 = 255.012 → rounded up to the cent → 255.02 (NOT minimum_payment 637.50).
- "Full amount too much" → 10.2: floor once, for the deadline (she named no day), rest stays overdue. She accepts the amount and names Monday the 19th → 3.3: next date numbered 19 = 2026-10-19; 9.1: business day, ≤ 10-22 → accepted.
- Promise p1 255.02 on 2026-10-19 → `promise`. The read-back of 255.02 on 10-19 (12.1) is not a second floor offer; the check says so.

## PUB-06 (variant 2) — Priya Nair, card 1903, 2125.10, 12 days late, now 2026-10-14T11:00; an amount below the floor
- "100 on Friday the 16th": own day and amount, not a refusal (11.2). 3.3: day number 16 → 2026-10-16, a business day ≤ 10-22 (9.1).
- 10.3: 100 < floor 255.02 → cannot be recorded; floor offered once for the same day as in 10.2 = the day she named → 255.02 on 10-16.
- She accepts → promise p1 255.02 on 2026-10-16 → `promise`. Records catch: 637.50 (minimum_payment) or recording 100.

## PUB-07 — Samuel Ortiz, personal loan 540.00, 5 days late, now 2026-10-14T11:00
- Band fresh; deadline = last bd of October = 10-29 (10-30 holiday).
- "No, towards the end of the month" = a vague period, not a flat refusal (11.2, 9.4) → ask once for the exact day.
- "Saturday the 24th" → 2026-10-24: not after the deadline, non-business → 9.3: business day before it: 10-23 is a bank holiday → 10-22 (Brief A's rule would give 10-26).
- Promise p1 540.00 on 2026-10-22 → `promise`.

## PUB-07 (variant 2) — Samuel Ortiz, personal loan 540.00, 5 days late, now_override 2026-10-23T11:00 (Friday, a bank holiday)
- Today is not a business day. Band fresh; deadline = last bd of October = 10-29 (after today, so no fallback to November).
- "Saturday the 24th" → 2026-10-24: non-business, not after the deadline → 9.3: the business day before it is 10-22 (10-23 is a holiday),
  which is before today → offer the next business day instead = Mon 2026-10-26.
- He accepts → promise p1 540.00 on 2026-10-26 → `promise`. Records catch: Brief A's calendar (10-26 is A's holiday → 10-27), offering the past
  10-22, or proposing the deadline 10-29 as if his day were a refusal.

## PUB-08 — Hannah Schmidt, card 5512, 180.00, 5 days late, now 2026-10-14T11:00
- 11.7: up to two business days to appear; no promise; add_note p1 `paid`.
- 13.4: no promise, every note paid → `paid` (reason none).

## PUB-09 — Victor Ionescu, personal loan 2100.00, 28 days late, now 2026-10-14T11:00
- 11.8: lower instalments → transfer_to_agent queue `restructuring`; no plan described.
- 12.6: transferred call → no notes. 13.2 → `transferred` / `plan_request`.

## PUB-10 — Grace Lin, card 7740, 365.00, 8 days late, now_override 2026-10-16T10:30 (Friday); fault: create_promise fails once
- Band due; deadline = last bd of next week = 10-22. Floor 43.80 (not used).
- "Cannot pay today" with no day/amount = a flat refusal; after it the next unused attempt is attempt 1 of the due band (11.1, 11.3) = full 365 on the 2nd bd after today: 10-19 (1st), 10-20 (2nd) → Tuesday 2026-10-20. The first ask uses no attempt.
- The script makes her accept the agent's first proposal whatever it is, so a wrong first proposal lands in the ledger: Brief A's attempt 1 from Fri 10-16 is the last bd of next week = 10-23 (a holiday here; 10-22 for an agent with this calendar but A's plan), a floor-first agent gives 43.80 on 10-22.
- 12.4: first create_promise fails → retry once with the same values → ok → "recorded" only now; 12.5 text-message sentence.
- Ledger: exactly one promise p1 365.00 on 2026-10-20 → `promise`.

## PUB-11 — Sofia Almeida, card 2288 220.00/9d, personal loan 640.00/9d, car loan 75.00/3d, now 2026-10-14T11:00
- 7.2: all three stated before any ask. p1, p2 band due → deadline 10-22; p3 fresh → 10-29.
- Car loan "paid this morning in the app" → 11.7: note p3 `paid`, no promise on it, continue.
- Card and loan: "no today, but both in full on Tuesday the 20th" → own day (11.2): 2026-10-20 is a business day ≤ 10-22 for both → 12.1 one read-back, one yes, create_promise twice.
- Promises p1 220.00 on 2026-10-20, p2 640.00 on 2026-10-20; notes [p3 paid]; 13.3 → `promise`.

## PUB-12 — Marcus Bell, card 9015 510.00/16d, personal loan 1320.00/16d, car loan 140.00/7d, now_override 2026-10-21T16:45 (Wednesday)
- Identity: phone 4401 wrong (1 of 2 allowed), asked again → 4410 passes; DOB asked once, passes.
- p1, p2 band overdue → deadline = 2nd bd after 10-21 = 10-26 (10-22, then 10-23 holiday, weekend, 10-26). p3 band due → deadline 10-29 (not used: dispute).
- Floors: card ceil(12% × 510 = 61.20) = 61.20; loan 440; car min(92, 140) = 92 (not used).
- "Cannot pay anything today" = flat refusal → products one by one, each from attempt 1 (11.1, 11.3). The script pins every refusal as a
  plain no (never "too much"), so the floor swap of 11.4 never triggers and all six proposals are made.
  - Card: A1 510 @ 10-22 (next bd), A2 510 @ 10-26 (deadline), A3 61.20 @ 10-26 → all refused → note p1 `refused`.
  - Loan: A1 1320 @ 10-22, A2 1320 @ 10-26, A3 440 @ 10-26 → all refused → note p2 `refused`.
  - Car loan: "never had a car loan" when the agent gets to it (possibly in reply to its opening proposal 140 @ 10-26) → 11.9 dispute, no
    further proposal, no promise → note p3 `dispute`.
- 13.4: no promise; notes not all paid; priority hardship > dispute > service_error > refused → `no_promise` / `dispute`
  (Brief B's "first product in get_account order" rule would give `refused`).

## PUB-13 — Elena Rossi, card 6604 300.00/4d, personal loan 900.00/20d, now 2026-10-14T11:00
- p1 fresh → deadline 10-29; p2 overdue → deadline = 2nd bd after 10-14 = 10-16. Floors 36.00 / 300 (not used).
- "Cannot pay today, both on Monday 26 October" → own day, not a refusal. 9.5 per product:
  - p1: 10-26 ≤ 10-29 and a business day (not a holiday in this calendar) → stays 2026-10-26.
  - p2: 10-26 > 10-16 → 9.2: its own deadline 2026-10-16, read back with the reason.
- She accepts; one read-back, one yes, two create_promise calls. 10-26 for the loan is handled by 9.2/9.5, not 11.8 (a day after the deadline is not a plan request).
- Promises p1 300.00 on 2026-10-26, p2 900.00 on 2026-10-16; no notes → `promise`.

## Where each rule change is exercised
| Change vs A+B | Cases |
|---|---|
| phone_last4 asked before date_of_birth | 01, 03, 12 (all verified cases) |
| two wrong answers end the check | 03 (a third question flips the outcome), 12 (one wrong is still fine) |
| three bands with new thresholds 1–5 / 6–15 / 16–45 | 07, 08, 11-p3, 13-p1 fresh; 01, 04, 06, 10, 11-p1/p2, 12-p3 due; 05, 09, 12-p1/p2, 13-p2 overdue |
| fresh deadline = last business day of the current month (next month if today or earlier) | 07, 07-v2, 13-p1; the next-month fallback is not reached by any case (all call days before 10-29) |
| due deadline = last business day of next week | 04 (holiday 10-30 pulls it to 10-29), 04-v2, 06, 06-v2, 10, 11 |
| overdue deadline = 2nd business day after today | 12 (holiday 10-23 pushes it to 10-26), 13-p2 |
| attempt plans (1 / 2 / 3 attempts, new days) | 10 (first proposal must be Tue 20 Oct, now in the records), 12 (six proposals, exact amounts and days), 04-v2 (due attempt 1 day 10-21 in the records) |
| card floor = 12% of past_due rounded up to the cent | 06 (255.02, not 637.50), 06-v2 (records), 12 (61.20 in attempt 3) |
| car-loan floor = 2 × instalment capped at past_due | 04-v2 (800.00 in the records); 04 and 12-p3 only in derivation |
| 10.2 "too much" is no refusal; 10.2 floor offer first, for the deadline | 04-v2 (skipping it changes the recorded day), 06 |
| 10.3 amount below the floor → floor once for the named day | 06-v2 (records) |
| 11.4 floor swap after "too much" | 04-v2 (attempt 1 = 800 on 10-21, not 1250) |
| 11.4 skip of a repeated offer | not exercised in records (04-v2 would reach it only if she refused attempt 1 too) |
| named closed day → business day BEFORE it; before today → next business day | 07 (Sat 24 → Thu 22, Fri 23 being a holiday), 07-v2 (Sat 24 on a holiday call day → Mon 26) |
| a call on a non-business day | 02 (Saturday), 07-v2 (bank holiday) |
| other calendar (10-23, 10-30 holidays; 10-26 open) | 04, 07, 07-v2, 12, 13 |
| callback window: today or next two business days, 09:00–17:30 | 02 (Saturday call → Monday) |
| notes also for single-product customers | 05 (hardship), 08 (paid) |
| no_promise reason by priority, not first product | 12 (dispute beats refused) |
| renamed close reasons (callback_booked, security_failed, plan_request, …) | 02, 03, 09 |
| a day after the deadline is 9.2, never a plan request (11.8) | 04, 13 |
| bare weekday = next such day (3.3) | 02 ("Monday" on a Saturday) |
| rules with no record-level case (checked only through the brief's text): 4.3 not_confirmed, 5.4/5.5, 6.6 first "what is this about?", 11.10 agent_requested, 11.11, 11.13 with refused notes (same records as A+B, so it would not discriminate), 12.7 | none |
| "already paid" sentence: up to two business days | 08, 11 |
| new opening, full-name ask, first-ask sentence, text-message sentence | all |
