# Memo COL-M-2026-07 — amendments to the Early Collections Operating Policy, edition 4.2

**From:** Petra Lindqvist, Conduct & Policy
**To:** Early Collections (all); Dialer & Telephony Operations; digital assistant build
**Date:** 8 October 2026
**Effective:** immediately. There is no transition period: the human team applies this memo from today, and the digital assistant applies it to every call it makes, whatever the date of the call.
**Amends:** edition 4.2 of the Early Collections Operating Policy, clauses listed below

Freya Bank is fictional; all data in this memo is synthetic.

This memo amends edition 4.2. It applies to the human team and to the digital assistant alike. Each item names the clause it touches and gives the full replacement text, so that the extract circulated to the assistant build can be read together with this memo. Where the extract and this memo differ, this memo applies.

## 1. COL-1.2 — one more closure day

The board has declared Thursday 26 November 2026 a bank closure day (Founders' Day). The table in COL-1.2 now reads:

| Closure day | Weekday |
|---|---|
| 2026-10-26 | Monday |
| 2026-11-11 | Wednesday |
| **2026-11-26** | **Thursday** (new) |
| 2026-12-25 | Friday |
| 2027-01-01 | Friday |

Business-day counts skip the new date like any other closure day.

## 2. COL-2.4 — wrong-answer limit raised from two to three

Following the review of the June security-failure complaints, COL-2.4 is replaced in full by:

> **COL-2.4 Wrong answers.** A question that was answered wrongly may be asked again. Three wrong answers in total — on one question or spread over both — end the security check. The assistant then says nothing about the arrears, directs the customer to the mobile app or a branch, and closes as `not_verified` / `failed`.

## 3. COL-2.6 — new clause: swapped day and month

The identity service now returns `hint: "day_month_swapped"` when a date of birth arrives with day and month the other way round. The reserved clause COL-2.6 is filled as follows:

> **COL-2.6 Swapped day and month.** If `verify_identity` returns `hint: "day_month_swapped"`, the assistant asks the customer to say the month as a word and sends the date again. That retry is not counted as a wrong answer.

## 4. COL-3.2 — callback window

The callback hours move with the new shift pattern. COL-3.2 is replaced in full by:

> **COL-3.2 Callback window.** A callback is booked for today or the next business day, at a time from 10:00 to 19:00, both included. The callback's date and time together must lie after the date and time of the call (`now`): a callback for today must be at a time later than the time of the call; a callback on the next business day may be at any time in the window. The assistant calls `schedule_callback` with the `date` and the `time`, then closes as `not_reached` / `callback`.

## 5. COL-5.1 — latest promise date in the early band

For the early band the latest promise date moves from the tenth to the twelfth business day after today. The late band is unchanged. The table in COL-5.1 now reads:

| `days_late` | Band | Latest promise date | Persuasion attempts |
|---|---|---|---|
| 1–7 | early | twelfth business day after today | one |
| 8–45 | late | seventh business day after today | two |

## 6. COL-6.8 — vulnerable customers: Customer Support offer

COL-6.8 is replaced in full by:

> **COL-6.8 Vulnerable customers.** If the customer mentions an illness, a death in the family or the loss of their job, the assistant says one short sentence of sympathy and makes no persuasion attempt. It offers, once, to connect the customer with the Customer Support team. If the customer accepts, the assistant calls `transfer_to_agent` with `queue` `support` and closes as `transferred` / `support`. If the customer declines, every product that has not yet ended — no promise recorded for it and no note written for it — ends with reason `hardship` (one product: close as `no_promise` / `hardship`; several products: note `hardship` for each such product, CL-7). A product that had already ended before the customer mentioned the hardship keeps its own reason; its note is not rewritten. This clause takes precedence over COL-6.6 (persuasion attempts) and over COL-9.3 (restructuring). If the customer nevertheless names a date or an amount of their own, that promise is taken and recorded under COL-5, COL-6 and COL-7.

## 7. COL-6.9 — concessions withdrawn

The split-payment concession is withdrawn with immediate effect. COL-6.9 is replaced in full by:

> **COL-6.9 No concessions.** The assistant offers no discount, no waiver, no instalment plan and no other term that is not set out in this policy, in memo COL-M-2026-07 or in code list CL-7.

## 8. COL-7.5 — confirmation by text message

Postal confirmations stop with the pilot. COL-7.5 is replaced in full by:

> **COL-7.5 Confirmation.** After a promise has been recorded, the assistant says exactly: "You will receive a text message confirming this promise."

---

Questions to Conduct & Policy, ext. 3305.

Petra Lindqvist
Conduct & Policy, Freya Bank
