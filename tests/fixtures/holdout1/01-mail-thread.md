# FW: Digital assistant pilot — open points (mail thread, 7 to 9 October 2026)

*Exported from the Early Collections shared mailbox for the digital assistant build. Freya Bank is a fictional bank; every name, number, extension and customer in this thread is synthetic.*

---

**From:** Jonas Weber, Dialer & Telephony Operations
**To:** Ingrid Solheim, Head of Early Collections
**Cc:** Petra Lindqvist, Conduct & Policy; assistant-build (shared mailbox)
**Sent:** Friday 9 October 2026, 16:42
**Subject:** RE: RE: RE: Digital assistant pilot — open points
**Attachments:** 02-policy-extract.md (COL ed. 4.2, extract, cross-references added); 03-memo.md (COL-M-2026-07); 04-code-list.md (CL-7)

Ingrid,

forwarding the whole thread to the build mailbox so the vendor has it next to the policy extract, Petra's memo and the code list. I am re-attaching the extract with two cross-references to this thread added (COL-2.2 and COL-9.6); the text of the clauses is unchanged. And yes to your last point: the memo wins over the extract wherever the two differ.

My answers to this morning's questions are numbered below. They are binding for the assistant in the same way as the three attachments — Petra will fold them into the next edition of the policy, but the vendor does not wait for that. Everything from the earlier mails still stands.

**1. What the dialer hands to the assistant.** At the start of each call the assistant receives the values below and nothing else. Nothing about the account is known before the tools are called.

| Field | Example | Use |
|---|---|---|
| `customer_id` | `c_4f2a…` | Goes into the body of every single tool call. |
| `first_name`, `last_name` | `Daniel`, `Reyes` | The person we are trying to reach. |
| `title` | `Mr` or `Ms` | The customer is addressed as title plus last name. |
| `now` | `2026-10-14T11:00` | Date and time of the call. Every date rule in the policy — business-day counts, latest promise dates, the callback window — is worked out from this value. The assistant must not use the clock of the machine it runs on. |

**2. "Next Friday".** Our convention, the same one the human team uses: "next <weekday>" is that weekday in the calendar week after the current one; "this <weekday>" is the one in the current week. A customer who says "next Friday" on a Friday therefore means the Friday seven days later, not the day of the call.

**3. Counting business days.** "The Nth business day after today" never counts today. Worked example for the test team: for a call on Thursday 8 October, the 7th business day after today is Monday 19 October (9, 12, 13, 14, 15, 16, 19). Closure days are skipped exactly like weekends — and note that the memo adds one closure day to the table in COL-1.2.

**4. "Am I talking to a robot?"** The assistant says that it is Freya Bank's digital assistant and carries on with the call. No hand-off.

**5. "Is this a scam?"** The assistant tells the customer that they can verify the call by phoning Freya Bank's customer service number, and carries on. If 4 or 5 comes as the reply to the "Am I speaking with…" question, the assistant answers first and then puts the identification question again; that repeat is the second and final ask under COL-2.2.

**6. Questions the tools cannot answer.** Interest rates, why a fee was charged, when the letter went out, what happens if they miss the date: if the answer is not in a tool result, the assistant says that it does not have that information. It does not invent figures, dates or reasons.

**7. The amount question.** Repeating it because it came up again on the vendor call: the assistant never asks "how much can you pay?", in any wording. The assistant proposes every amount; the customer accepts it or proposes their own (COL-6.1 and COL-6.4).

**8. Ending the call.** Thank the customer and say goodbye, then `close_call`. Exactly one `close_call` per call, and it is the last tool call; the ledger accepts nothing after it (CL-7, section A).

Have a good weekend. The car park barrier is finally fixed, by the way.

Jonas

--
Jonas Weber
Dialer & Telephony Operations, Freya Bank
ext. 2190

> **From:** Ingrid Solheim
> **Sent:** Friday 9 October 2026, 11:05
> **To:** Jonas Weber
> **Cc:** Petra Lindqvist; assistant-build
> **Subject:** RE: RE: Digital assistant pilot — open points
>
> Jonas, Petra,
>
> I read the extract and the memo last night. Before I sign off the pack for the vendor I want a few things in writing:
>
> 1. What exactly does the dialer give the assistant? The vendor asked whether the assistant knows the product before the call. (It must not; that is the whole point of the "nothing before security" rule.)
> 2. "Next Friday" — the human team argue about this every single week. Which convention are we giving the assistant?
> 3. Can you give the test team a worked example of a business-day count? They keep counting the day of the call.
> 4. What does the assistant say when a customer asks whether it is a machine, or whether the call is a scam? We get both every day.
> 5. What does it say when asked something it cannot know?
> 6. The vendor's draft prompt had "how much could you manage?" in it. I assume that is out.
> 7. Confirm the closing mechanics for the ledger, please.
>
> Also: Petra's memo changes the callback hours and the early-band latest date, among other things. The vendor should read the memo as overriding the extract wherever they differ — correct?
>
> Ingrid
>
> --
> Ingrid Solheim
> Head of Early Collections, Freya Bank
> ext. 2044

>> **From:** Jonas Weber
>> **Sent:** Thursday 8 October 2026, 17:20
>> **To:** Ingrid Solheim
>> **Cc:** Petra Lindqvist; assistant-build
>> **Subject:** RE: Digital assistant pilot — open points
>>
>> Ingrid,
>>
>> Attached: the extract of the Early Collections Operating Policy (edition 4.2, sections COL-1 to COL-9), Petra's memo COL-M-2026-07 of today, which amends it with immediate effect, and code list CL-7 with the close codes, product notes and transfer queues the ledger accepts. The three documents together are the specification for the assistant; it must follow all of them, with the memo taking precedence over the extract.
>>
>> On the tool side nothing changes for the pilot: the same seven tools as the human desktop (`verify_identity`, `get_account`, `create_promise`, `add_note`, `schedule_callback`, `transfer_to_agent`, `close_call`), spelled as in `openapi.json`. The ledger does not police policy — it will store a promise on a Sunday or past the latest date without complaint — so the assistant has to get it right by itself.
>>
>> One thing from the dry runs with the human team's scripts: the identity service now sends a hint back when a date of birth arrives with day and month swapped. Petra has put the handling into the memo so that it is in the policy and not only in my head.
>>
>> Jonas

>>> **From:** Ingrid Solheim
>>> **Sent:** Wednesday 7 October 2026, 09:12
>>> **To:** Jonas Weber; Petra Lindqvist
>>> **Cc:** assistant-build
>>> **Subject:** Digital assistant pilot — open points
>>>
>>> All,
>>>
>>> Kick-off for the digital assistant on the early-arrears queue: customers between one and 45 days late, on up to three products. Same policy as the human team, no special treatment. Two things I will not compromise on: it opens by saying what it is and that the line is recorded, and it says nothing about money or products to anyone who has not passed security — not to the customer, not to the spouse who "handles the finances", nobody.
>>>
>>> Jonas, please pack the policy extract, Petra's memo and the code list for the vendor. Petra, anything that still lives only in e-mails or in people's heads goes into the memo, please.
>>>
>>> The Q4 offsite agenda is in the shared folder; add your items by Friday.
>>>
>>> Ingrid
