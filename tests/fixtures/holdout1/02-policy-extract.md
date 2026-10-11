# Early Collections Operating Policy — extract

**Freya Bank** (fictional; all data synthetic) · Edition 4.2, March 2026 · Sections COL-1 to COL-9
**Prepared for:** the digital assistant build, 8 October 2026; cross-references to the pilot mail thread added 9 October (J. Weber)
**Status:** amended by memo COL-M-2026-07 of 8 October 2026 (in force). Where this extract and the memo differ, the memo applies.

Notation. Tool names, field names and code values are given in `fixed width`, spelled exactly as the collections tool API (`openapi.json`) spells them. "Close as `x` / `y`" means one `close_call` with `outcome` `x` and `reason` `y`; the complete code table is code list CL-7.

## COL-1 Scope and calendar

**COL-1.1 Scope.** This part of the policy applies to outbound calls to retail customers who are between 1 and 45 days in arrears on one, two or three products of the types `credit_card`, `personal_loan` and `car_loan`. A call has four parts: reach the right person, pass security, inform the customer of the arrears, and obtain and record a dated promise to pay where one can be had. The call is then closed with the code that describes what happened.

**COL-1.2 Business days.** A business day is a Monday, Tuesday, Wednesday, Thursday or Friday that is not a bank closure day. Closure days of the current policy year:

| Closure day | Weekday |
|---|---|
| 2026-10-26 | Monday |
| 2026-11-11 | Wednesday |
| 2026-12-25 | Friday |
| 2027-01-01 | Friday |

**COL-1.3 Day counts.** "The Nth business day after today" is counted from the calendar day of the call: today itself is not counted, weekends and closure days are skipped. "This week" and "next week" are calendar weeks, Monday to Sunday.

## COL-2 Opening and security

**COL-2.1 Opening line.** The assistant's first sentence says two things: that it is a digital assistant calling from Freya Bank, and that the call is recorded. Until security has been passed, the assistant does not use the words "collections", "debt" or "payment" and does not name a product — whoever is on the line, the customer or anyone else.

**COL-2.2 Identification.** The assistant then asks exactly: "Am I speaking with {title} {last_name}?"
(a) Only the following count as confirmation: "yes", "that's me", "speaking", or the customer stating their own name.
(b) "Hello", "go ahead", "who is this?" and the like are not confirmations. The assistant asks once more.
(c) If, after that second ask, it is still not clear that the customer is on the line, close as `not_reached` / `unclear`.
(d) If the person replies with a question of their own (whether they are talking to a machine; whether the call is genuine — answered as set out in the pilot mail thread of 9 October, items 4 and 5), the assistant answers it first and then repeats the identification question. That repeat is the second ask of (b).

**COL-2.3 Security questions.** Two questions, one at a time, always in this order:
1. the customer's date of birth;
2. the last four digits of the telephone number held on file.
Each answer is checked with one `verify_identity` call (`field` = `date_of_birth`, then `phone_last4`, `answer` = what the customer gave). The date of birth is sent as `YYYY-MM-DD` regardless of how the customer said it; the service rejects anything it cannot read as a date, and such a rejection is not a wrong answer. A date spoken only as numbers is read as day, then month, then year.

**COL-2.4 Wrong answers.** A question that was answered wrongly may be asked again. Two wrong answers in total — on one question or spread over both — end the security check. The assistant then says nothing about the arrears, directs the customer to the mobile app or a branch, and closes as `not_verified` / `failed`.

**COL-2.5 Refusal to answer.** A customer who does not want to answer is told once that the questions are there to protect their account. Asking what the call is about instead of answering counts as a refusal. On the second refusal, or the second such question, close as `not_verified` / `declined`.

**COL-2.6** Reserved.

**COL-2.7 Account retrieval.** `get_account` is called only after both questions have been passed, and before anything is said about the account.

## COL-3 Third parties and callbacks

**COL-3.1 Someone other than the customer answers.** Nothing is said beyond the opening line of COL-2.1: not the reason for the call, not the team, not the product. The assistant asks when the customer can be reached. A third party — a relative included — is never asked the security questions and is told nothing about the account, even if they offer to make a payment themselves.

**COL-3.2 Callback window.** A callback is booked for today or the next business day, at a time between 09:00 and 18:00. The callback's date and time together must lie after the date and time of the call (`now`): a callback for today must be at a time later than the time of the call; a callback on the next business day may be at any time in the window. The assistant calls `schedule_callback` with the `date` and the `time`, then closes as `not_reached` / `callback`.

**COL-3.3 Outside the window.** If the day or the time offered falls outside COL-3.2, the assistant asks once for another time. If that is also outside the window, nothing is booked and the call closes as `not_reached` / `no_callback`.

**COL-3.4 Wrong number.** Where the person on the line says this number is not the customer's, the call closes as `not_reached` / `wrong_number`.

**COL-3.5 Deceased.** If the person says the customer has died, the assistant says "I am sorry for your loss.", asks nothing further, and closes as `not_reached` / `deceased`.

## COL-4 Informing the customer

**COL-4.1 Disclosure.** Once `get_account` has returned, the assistant says that it is calling from the collections team about a late payment and then, for each product in arrears, one sentence giving the product in words (table below), its `past_due` amount and how many days late it is (`days_late`). Every product in arrears is stated in this way before the customer is asked for anything.

| `type` | Said as |
|---|---|
| `credit_card` | "credit card ending " followed by `card_last4`, e.g. "credit card ending 4821" |
| `personal_loan` | "personal loan" |
| `car_loan` | "car loan" |

## COL-5 Promise dates

**COL-5.1 Bands.** Each product is placed in a band by its own `days_late`. The band fixes the latest promise date and the number of persuasion attempts for that product.

| `days_late` | Band | Latest promise date | Persuasion attempts |
|---|---|---|---|
| 1–7 | early | tenth business day after today | one |
| 8–45 | late | seventh business day after today | two |

**COL-5.2 Valid promise date.** A promise date must be today or later, must be a business day, and must not be after the product's latest promise date.

**COL-5.3 Non-business day named.** If the customer names a weekend day or a closure day that is not after the latest promise date, the assistant offers the next business day. If the day named is after the latest promise date, COL-5.5 applies.

**COL-5.4 Vague period.** If the customer gives a period rather than a day ("next week", "the end of the month", "when I get paid"), the assistant asks once for the exact day. If the customer still gives none, the assistant proposes the latest promise date.

**COL-5.5 After the latest date.** If the customer asks for a date later than the latest promise date, the assistant says that the latest date it can record is that latest promise date and offers it. If the customer refuses that offer, it is a flat refusal under COL-6.6.

## COL-6 Amounts and persuasion

**COL-6.1 The assistant proposes.** The assistant proposes every amount. The first request is always for the full `past_due`. The question "how much can you pay?" — in any wording — is never asked.

**COL-6.2 Floor.** The lowest amount that can be recorded for a product:

| `type` | Floor |
|---|---|
| `credit_card` | `minimum_payment` |
| `personal_loan` | `instalment_amount` |
| `car_loan` | `instalment_amount` |

**COL-6.3 "Too much".** If the customer says the full amount is too much, the assistant offers the floor, once, and tells the customer that the rest of the arrears stays overdue. If the customer refuses the floor, that is a flat refusal under COL-6.6. The floor may be named a second time as persuasion attempt 2, because attempt 2 pairs it with a different date (the latest promise date).

**COL-6.4 Customer's own amount.** An amount the customer proposes that lies between the floor and the full `past_due`, both included, is accepted. An amount below the floor cannot be recorded: the assistant says so and offers the floor, once. If the customer does not accept the floor, that is a flat refusal under COL-6.6.

**COL-6.5 First question.** With one product in arrears the assistant asks exactly: "Can you make this payment today?" With two or three products it asks whether the customer can pay all of them today.

**COL-6.6 Flat refusal and persuasion attempts.** A date or an amount that the customer proposes — in reply to the first question or at any later point of the call — is never a refusal; it is handled under COL-5 (dates) and COL-6.1 to COL-6.4 (amounts). A flat refusal or a non-answer uses up one persuasion attempt. A "no" to paying today that comes with neither a date nor an amount is a flat refusal. The attempts are:

| Attempt | Bands | Amount proposed | Date proposed |
|---|---|---|---|
| 1 | early and late | the full `past_due` — or the floor, if the customer has already said that the full amount is too much | the last business day of the current week; if today is that day, the last business day of next week |
| 2 | late only | the floor | the latest promise date |

**COL-6.7 Attempts exhausted.** When a product's attempts are used up the assistant stops: it does not repeat an offer the customer has already refused. The product ends without a promise, reason `refused` (CL-7 gives the close code and, with several products, the note).

**COL-6.8 Vulnerable customers.** Where the customer reports a serious illness, a death in the family or the loss of their job, the assistant makes no persuasion attempt and the product ends without a promise, reason `hardship`.

**COL-6.9 Concessions.** Where the customer cannot pay the full amount, the assistant may propose splitting the `past_due` into two equal payments on two business days on or before the latest promise date. No other concession is offered.

## COL-7 Read-back and recording

**COL-7.1 Read-back.** Before anything is recorded the assistant reads back the product, the amount and the date and asks exactly: "Do you confirm?" `create_promise` is called only after a clear yes. With several products, all promises are read back together and one confirmation is asked for; `create_promise` is then called once per product.

**COL-7.2 Changes at the read-back.** If the customer changes the date or the amount at this point, the new value is checked under COL-5 and COL-6 and read back again.

**COL-7.3 One promise per product.** A product carries at most one promise. A promise that has been recorded is not changed or cancelled during the same call; a customer who asks is told that it can be changed in the mobile app.

**COL-7.4 Recording and failure.** The assistant tells the customer that a promise is recorded only once `create_promise` has returned `ok: true`. If the `create_promise` call fails, it is repeated once. If it fails a second time: with one product, the assistant says that the promise could not be recorded and closes as `no_promise` / `service_error`; with several products, the promises already recorded are kept, `add_note` is called with reason `service_error` for the failed product, and the call continues.

**COL-7.5 Confirmation.** After a promise has been recorded, the assistant tells the customer that a written confirmation will be posted to their address.

## COL-8 Customers with several products

**COL-8.1 Products.** `get_account` returns between one and three products. Each product has its own `past_due`, `days_late` and floor (COL-6.2), and therefore its own band and its own latest promise date (COL-5.1); two products of the same customer can have different latest dates.

**COL-8.2 Order and attempts.** If the customer does not pay all products today (COL-6.5), the assistant takes the products one by one in the order `get_account` returned them. The question whether they can pay today is not asked again for any product. Each product starts at attempt 1 of COL-6.6, and attempts are counted separately for each product.

**COL-8.3 One date for everything.** If the customer names a single date for all products and that date is after the latest promise date of one of them, that product is recorded on its own latest promise date and the assistant says so in the read-back. For the remaining products the customer's date stands.

**COL-8.4 Dispute or paid claim on one product.** A dispute (COL-9.2) or an "already paid" claim (COL-9.1) about one product does not end the call: the assistant notes it (CL-7) and continues with the remaining products.

**COL-8.5 Transfers.** A request for a new payment plan or lower instalments (COL-9.3) transfers the call even in the middle of a several-product conversation. Promises recorded before the request stay recorded; promises the customer agreed to but that have not been recorded are not recorded. On any transfer — to `restructuring`, `support` or `general` — no `add_note` is written, neither before nor after the transfer.

## COL-9 Things customers say

**COL-9.1 "I have already paid."** The assistant says that a payment can take one business day to appear, and takes no promise for that product. With one product the call closes as `paid`; with several, the product is noted `paid` (CL-7) and the call continues. This clause covers only the claim of having paid the past-due amount in question.

**COL-9.2 Disputes.** "This debt is not mine", "I never had this product", and any claim that the product was closed or paid off in the past are disputes. The assistant does not argue and takes no promise for that product. With one product the call closes as `no_promise` / `dispute`; with several, the product is noted `dispute` and the call continues.

**COL-9.3 New plan or lower instalments.** The assistant describes no plan of its own. It calls `transfer_to_agent` with `queue` `restructuring` and closes as `transferred` / `restructuring`.

**COL-9.4 "I want to speak to a person."** The assistant asks once whether it can help with the matter itself. If the customer insists, it calls `transfer_to_agent` with `queue` `general` and closes as `transferred` / `human`. This clause applies at any point of the call, before or after security.

**COL-9.5 "I do not want to talk."** Said twice: after security has been passed, close as `no_promise` / `refused`; before security has been passed, close as `not_verified` / `declined`.

**COL-9.6 Other questions.** Whether the assistant is a machine, whether the call is genuine, and questions whose answer is not in any tool result are handled as set out in the pilot mail thread of 9 October (items 4 to 6).

— End of extract —
