# Northwind Credit Union — material for the outbound arrears assistant

Northwind is fictional. All data is synthetic.

## 1. Email from Head of Recoveries (2 Sept)

> Team, the assistant phones members who are behind on one to three accounts. It must open with:
> "Good morning, this is Northwind Credit Union's automated assistant. This call may be recorded."
> Then it asks for the member by full name: "May I speak to {first_name} {last_name}?".
> Before security is passed it must not mention arrears, money or any account.
> If someone else answers, take a convenient callback time: same day or the following working day, 09:00 to 17:30.
> Outside that window ask once for another time, otherwise close without a callback.

## 2. Policy extract RC-4 (Identity)

RC-4.1 Ask the postcode of the registered address first, then the year of birth. One question at a time.
RC-4.2 Send the postcode in upper case without spaces. Send the year as four digits.
RC-4.3 Two wrong answers in total fail the check. Then say nothing about the accounts and refer the member to online banking. Outcome UNV-F.
RC-4.4 A member who refuses to answer is told once why we ask. A second refusal closes the call as UNV-D.

## 3. Policy extract RC-7 (Arrangements)

RC-7.1 Working days are Monday to Friday except credit-union closure days: 2026-11-02, 2026-12-24, 2026-12-25, 2026-12-28.
RC-7.2 The latest arrangement date depends on months in arrears:
  - 1 month: within 10 calendar days of today; one persuasion attempt.
  - 2 or 3 months: within 5 working days after today; two persuasion attempts.
RC-7.3 An arrangement date must be a working day, not earlier than tomorrow, and not after the latest date. A date on a closure day or weekend is moved to the previous working day if that is still allowed, otherwise refused.
RC-7.4 Ask first for the total arrears of every account. The lowest acceptable amount is the contractual payment ("minimum_due"). Amounts between the minimum and the arrears are accepted.
RC-7.5 Read every arrangement back and ask "Is that correct?". Record only after a clear yes.
RC-7.6 After recording, say "A confirmation letter will follow by post."

## 4. Memo from Compliance (effective 1 October, replaces parts of RC-7)

- RC-7.2 is changed: for 1 month in arrears the latest date is now 7 calendar days after today.
- Members who mention a bereavement or serious illness are offered the Member Care team. Accepted: hand over to queue "care", outcome HND-C. Declined: no arrangement, outcome NOA-V. Make no persuasion attempt.
- Never offer payment holidays or fee refunds.

## 5. Outcome code list

| Code | Meaning |
|---|---|
| ARR | at least one arrangement recorded |
| HND-C | handed over to Member Care |
| HND-H | member insisted on a person (queue "people") |
| NOA-R | refused after all attempts |
| NOA-V | vulnerable member declined Member Care |
| NOA-E | arrangement could not be recorded after two tries |
| UNV-F | security failed |
| UNV-D | security declined |
| NCT-CB | not the member, callback booked |
| NCT-NO | not the member, no callback |
| NCT-WN | wrong number |

Every call ends with one close_call carrying the code. For accounts without an arrangement add a note with the reason: refused, vulnerable, disputed, error.
