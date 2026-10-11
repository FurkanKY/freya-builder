# Freya Bank services mock (Cloudflare Worker `freya-bank-mock`)

The seven voice services of the service contract (`sources/documents/2026-10-01-service-contract.md`)
as a pure table lookup over `test-environment/test-customers.json`. Deploy target
`https://freya-bank-mock.fky-freya.workers.dev`: it serves whatever was last deployed, so after any
change to `src/` run `npx wrangler deploy` from `mock/` (you run it) and check `/__health` (below)
before pointing a build or a replay at it. No dependencies.

| Route (all `POST`, also without the `/voice/v1` prefix) | Looked up by | Not in the file |
| --- | --- | --- |
| `/voice/v1/cards.list` | `data.customerNo` | 404 `FB_IVR_CHANNEL_102` WARNING |
| `/voice/v1/cards.balance` | `data.cardNumber` | 404 `FB_IVR_CHANNEL_120` WARNING |
| `/voice/v1/statement.week.get` | `data.cardNumber` | 404 `FB_IVR_CHANNEL_121` WARNING |
| `/voice/v1/statement.week.decide` | `data.cardNumber`, then `String(data.newStatementWeek)` | 400 `INVALID_ARGUMENTS_ERROR` |
| `/voice/v1/statement.week.change` | `data.cardNumber`, then `String(data.newStatementWeek)` | 400 `INVALID_ARGUMENTS_ERROR` |
| `/voice/v1/contact.email.get` | `data.customerNo` | 400 `INVALID_ARGUMENTS_ERROR` |
| `/voice/v1/statement.pdf.send` | `data.customerNo` (only) | 404 `FB_IVR_CHANNEL_107` WARNING |
| `/oauth2/token` (form or JSON) | nothing | always `{"access_token":"test-token","token_type":"Bearer","expires_in":1800}` |

- A request the file has an entry for gets **exactly** that entry's `response` with its `http`
  status, after `delaySeconds` when the entry has one (only `94907600` / `cards.balance` /
  `540000******7211`: 12 s). Numbers go through `JSON.parse`/`JSON.stringify`, so `0.0` in the
  file is sent as `0` and `12000.0` as `12000` (the same JSON values; nothing else differs).
- Request envelope `{data:{...}, call:{...}}`; only `data` decides. Fields at the top level are
  used when there is no `data` (also `data` as a JSON string). Token, headers, `call` and
  `aiFlow` are never checked.
- Lenient input: `customerNo` string or number, spaces trimmed, digits only; `newStatementWeek`
  `3`/`"3"`/`" 3 "`/`"03"`/`"3. hafta"`, or one week word with only `hafta`/`week`-style filler
  (`bir`/`birinci`/`ilk`/`first`/`one` .. `dört`/`dördüncü`/`fourth`/`four`, Turkish letters
  folded: `"üçüncü hafta"`, `"İLK"`; logged as `field_warning`; `"bir sonraki hafta"`, two weeks
  named, or any other word -> 400); card numbers: exact key, then normalised (spaces, dashes, `X`/`•`/`#`
  masks of any count), then first 6 + last 4 (>= 10 digits sent, also a full 16-digit number),
  then first 4 + last 4 (the `cards.balance` masking `5400********1234`) if exactly one card in
  the file has them; never the last 4 alone (a made-up number that only ends like a card would get
  another customer's answer) -> not found. Other spellings (`customerNumber`, `cardNo`, `statementWeek`) are
  served with a `field_warning` in the log.
- Missing/empty required field -> 400 `INVALID_ARGUMENTS_ERROR` naming it (`customer number
  cannot be empty`, `card number cannot be empty`, `newStatementWeek cannot be empty`,
  `intAddressInfoType cannot be empty` when that key is present but empty). Lenient (served,
  logged as `field_warning`): a missing `statementDay`, a missing `intAddressInfoType`, and
  `statement.pdf.send`'s `cardNumber`/`currencyType`/`statementDate`/`emailAddress` (missing, of
  another customer, not the registered address, not the issued statement date).
- A week the file has no entry for (the card's current week, or outside 1-4) -> 400.
- An unfilled placeholder (`{{var}}` or `%7B%7B...` anywhere in a value, also an unquoted
  `{{var}}` in the JSON) is an unknown value like any other: the service's 404/400 above, never
  another customer's data; the log names the fields in `template_warning`. The compiled tools'
  panel defaults (`{"call":"{{call}}","data":"{{data}}"}`) get 400 `customer number cannot be
  empty` / `card number cannot be empty`.
- Errors have the contract's shape: `{"result":{guid, returnCode, messageText, code, message,
  type, details:{guid, rootCause, errorOrigin:"ivr-gateway-test:ivr-channel-v0"}}}`, no `data`;
  `guid` is 32 lowercase hex. Unknown path -> 404 `NOT_FOUND` (message lists the routes), GET on a
  route -> 405, bad JSON -> 400 `INVALID_ARGUMENTS_ERROR`, a mock crash -> 500 `FBE00099`.
- Stateless: a week change or a PDF send never changes a later answer. They are recorded for
  `/__state` only; concurrent calls for one customer do not interfere.

| File | What it holds |
| --- | --- |
| `src/data.js` | GENERATED: the test customers file as a JS module (`node tools/make-data.mjs <case>/test-environment/test-customers.json`) |
| `src/routes.js` | the routes, lookup indexes, card/customer/week matching, the contract error body, `settings` |
| `src/worker.js` | router, CORS, body parsing, request log, the `MockState` Durable Object |
| `src/state.js` | observation records (week changes, PDF sends), capped at 300 |
| `src/util.js` | `json`, `error`, `digits` and other generic helpers |
| `test/run.mjs` | every file entry plus all edge cases (`node test/run.mjs`) |

## Test

```sh
node test/run.mjs                      # reads ../final/drive/test-environment/test-customers.json
CASE_JSON=<path> node test/run.mjs     # or another copy of the file
```

It sends every entry of the file (617: every customer, service, card and week; customer numbers
as string and number, weeks as string and number) and compares status and JSON text exactly,
then leniency, not-found, missing fields, template variables, paths, token, statelessness, the
delay (scaled down with `settings.DELAY_SCALE`), the Durable Object, and the values the six
examples in `example-scenarios.md` rely on.

## Watch it (after you deploy)

```sh
curl -s https://freya-bank-mock.fky-freya.workers.dev/__health    # this mock: {"ok":true,"routes":8,"customers":34,"store":"durable_object"}
curl -s 'https://freya-bank-mock.fky-freya.workers.dev/__log?limit=5'  # requests: body, status, matched, card_match, field_warning, response
curl -s https://freya-bank-mock.fky-freya.workers.dev/__state     # week changes and PDF sends per customer
curl -s -X POST https://freya-bank-mock.fky-freya.workers.dev/__reset
```

Deploy (you run it): `npx wrangler deploy` from `mock/`. Then, with the example calls:
`node tools/replay.mjs <calls> --url https://freya-bank-mock.fky-freya.workers.dev/voice/v1 --ignore guid,messageText,message,rootCause`. State and log live in one Durable
Object (`MockState` "main", binding `MOCK`, SQLite-backed, Free plan).
