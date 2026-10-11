# Code list CL-7 — call close codes, product notes and transfer queues

**Freya Bank** (fictional; all data synthetic) · Collections ledger codes · Version 7, 8 October 2026 · Owner: Dialer & Telephony Operations
Applies to the human desktop and to the digital assistant. Every value below is the exact string the ledger accepts (`openapi.json`). Clause references are to the Early Collections Operating Policy, edition 4.2, as amended by memo COL-M-2026-07.

## A. Closing a call (`close_call`)

A.1 Every call ends with exactly one `close_call`. It is the last tool call of the call; the ledger accepts nothing after it.
A.2 `close_call` carries an `outcome` and, for every outcome except `promise` and `paid`, a `reason` from the table.
A.3 The assistant thanks the customer and says goodbye before `close_call`.

| `outcome` | `reason` | Situation | Clause |
|---|---|---|---|
| `promise` | — (none) | at least one promise was recorded in this call | COL-7.4; rule C.1 |
| `paid` | — (none) | the customer says the past-due amount is already paid (one product), or every product is noted `paid` (several) | COL-9.1; rule C.2 |
| `transferred` | `restructuring` | the customer asked for a new plan or lower instalments | COL-9.3, COL-8.5 |
| `transferred` | `human` | the customer insisted on a person | COL-9.4 |
| `transferred` | `support` | a vulnerable customer accepted the Customer Support offer | COL-6.8 as amended |
| `no_promise` | `refused` | the persuasion attempts are used up; or the customer said twice, after security, that they do not want to talk | COL-6.7, COL-9.5 |
| `no_promise` | `hardship` | a vulnerable customer declined Customer Support | COL-6.8 as amended |
| `no_promise` | `dispute` | the debt or the product is disputed | COL-9.2 |
| `no_promise` | `service_error` | `create_promise` failed twice, one product | COL-7.4 |
| `not_verified` | `failed` | the wrong-answer limit was reached | COL-2.4 as amended |
| `not_verified` | `declined` | the customer refused the security questions (second refusal, or second "what is this about?"); or said twice, before security, that they do not want to talk | COL-2.5, COL-9.5 |
| `not_reached` | `callback` | a third party answered and a callback was booked | COL-3.2 as amended |
| `not_reached` | `no_callback` | a third party answered; both times offered were outside the window | COL-3.3 |
| `not_reached` | `wrong_number` | the number does not belong to the customer | COL-3.4 |
| `not_reached` | `deceased` | the customer has died | COL-3.5 |
| `not_reached` | `unclear` | still unclear after the second ask who is on the line | COL-2.2 |

With several products the reason of a `no_promise` close is chosen by rule C.3.

## B. Product notes (`add_note`)

B.1 A note records why one product ended without a promise. `add_note` takes the `product_id` that `get_account` returned for that product and a `reason` from the table below.
B.2 Notes are written only on calls where `get_account` returned two or more products. With a single product the close code carries the result and no note is written.
B.3 With two or more products, every product that ends without a recorded promise gets exactly one note — also when no product at all gets a promise.
B.4 Exception: on a call that is transferred (any queue), no note is written, neither before nor after the transfer (COL-8.5).

| `reason` | When | Clause |
|---|---|---|
| `refused` | the attempts for that product are used up | COL-6.7 |
| `hardship` | a vulnerable customer declined Customer Support and the product had not yet ended at that point (no promise recorded, no note written); a product that had already ended keeps its own note | COL-6.8 as amended |
| `dispute` | that product is disputed | COL-9.2, COL-8.4 |
| `paid` | the customer says that product is already paid | COL-9.1, COL-8.4 |
| `service_error` | `create_promise` for that product failed twice | COL-7.4 |

## C. Precedence with several products

C.1 If at least one promise was recorded, the outcome is `promise` — unless the call was transferred, in which case the outcome is `transferred` with the reason of that transfer. The same holds with one product: a transfer that follows a recorded promise closes as `transferred` with that transfer's reason.
C.2 If no promise was recorded and every product is noted `paid`, the outcome is `paid`.
C.3 If no promise was recorded and C.2 does not apply, the outcome is `no_promise` and the reason is the note reason of the first product, in `get_account` order, whose note is not `paid`.

## D. Transfer queues (`transfer_to_agent`)

| `queue` | Who | Close code |
|---|---|---|
| `restructuring` | Restructuring desk: new plans, lower instalments | `transferred` / `restructuring` |
| `general` | General queue: the customer insists on a person | `transferred` / `human` |
| `support` | Customer Support: vulnerable customers | `transferred` / `support` |

## E. Callbacks (`schedule_callback`)

`date` as `YYYY-MM-DD`, `time` as `HH:MM`. Window and rules: COL-3.2 as amended by memo COL-M-2026-07, and COL-3.3.
