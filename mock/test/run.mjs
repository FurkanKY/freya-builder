// No-dependency test of the bank-services mock: node test/run.mjs (from mock/).
//
// 1. Every entry of test-customers.json (every customer, service, card, week) through the worker's
//    fetch: exact status and exact body (same JSON text as JSON.stringify of the file's entry, so
//    field order, nulls and values all count; 0.0 in the file is 0, the same JSON value).
//    The file is read from $CASE_JSON, else <mock>/../final/drive/test-environment/test-customers.json,
//    else the embedded src/data.js (then the embedded copy is not checked against the file).
// 2. Leniency, not-found, missing fields, template variables, paths, token, statelessness, the
//    delay entry, the Durable Object, and the answers example-scenarios.md relies on.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import worker, { MockState } from '../src/worker.js';
import { BASE, routes, settings } from '../src/routes.js';
import DATA from '../src/data.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const say = console.log;
const lines = []; // the worker's console.log lines (one per request), kept out of the output
console.log = (s) => lines.push(s);

const casePath = process.env.CASE_JSON ?? path.join(here, '../../final/drive/test-environment/test-customers.json');
const FILE = fs.existsSync(casePath) ? JSON.parse(fs.readFileSync(casePath, 'utf8')) : null;
const SRC = FILE ?? DATA;

// One request through the Worker (env {}: in-process router; env.MOCK: through the DO).
async function call(method, p, body, headers = {}, env = {}) {
  const init = { method, headers: { 'content-type': 'application/json', ...headers } };
  if (body !== undefined) init.body = typeof body === 'string' ? body : JSON.stringify(body);
  const res = await worker.fetch(new Request('https://mock.test' + p, init), env, {});
  const text = res.status === 204 ? '' : await res.text();
  return { res, status: res.status, text, data: text ? JSON.parse(text) : null };
}
const post = (op, data, extra = {}) => call('POST', `${BASE}/${op}`, { data, call: { ani: '05550000000', lang: 'tr' }, ...extra });
const lastLog = () => JSON.parse(lines[lines.length - 1]);

let n = 0;
let checks = 0;
async function test(name, fn) {
  await fn();
  n++;
  say('ok', name);
}

// The exact answer: status and JSON text.
function exact(r, entry, what) {
  checks++;
  assert.equal(r.status, entry.http, `${what}: status`);
  assert.equal(r.text, JSON.stringify(entry.response), `${what}: body`);
}

// A contract error body (section 4): result only, guid 32 hex, code/message pairs equal.
function contractError(r, status, code, type, message) {
  checks++;
  assert.equal(r.status, status, `status ${r.status} ${r.text}`);
  assert.deepEqual(Object.keys(r.data), ['result']);
  const x = r.data.result;
  assert.deepEqual(Object.keys(x), ['guid', 'returnCode', 'messageText', 'code', 'message', 'type', 'details']);
  assert.deepEqual(Object.keys(x.details), ['guid', 'rootCause', 'errorOrigin']);
  assert.match(x.guid, /^[0-9a-f]{32}$/);
  assert.equal(x.details.guid, x.guid);
  assert.equal(x.returnCode, code);
  assert.equal(x.code, code);
  assert.equal(x.messageText, x.message);
  assert.equal(x.type, type);
  assert.equal(x.details.errorOrigin, 'ivr-gateway-test:ivr-channel-v0');
  assert.equal(typeof x.details.rootCause, 'string');
  if (message instanceof RegExp) assert.match(x.message, message);
  else if (message) assert.equal(x.message, message);
  return x;
}
const invalid = (r, message) => contractError(r, 400, 'INVALID_ARGUMENTS_ERROR', 'ERROR', message);

const C = Object.fromEntries(SRC.customers.map((c) => [c.customerNo, c]));
const svc = (no, s) => C[no].services[s];

await call('POST', '/__reset');

// ---------------------------------------------------------------- data and basics

await test('embedded data equals the case file (or the file is not here)', async () => {
  if (!FILE) {
    say('   (case file not found at', casePath, '- the embedded copy is used as the reference)');
    return;
  }
  assert.equal(JSON.stringify(DATA), JSON.stringify(FILE));
});

await test('health, route list, CORS', async () => {
  const h = await call('GET', '/__health');
  assert.equal(h.status, 200);
  assert.deepEqual(h.data, { ok: true, routes: 8, customers: SRC.customers.length, store: 'memory' });
  assert.equal(h.res.headers.get('access-control-allow-origin'), '*');
  const root = await call('GET', '/');
  assert.deepEqual(root.data.routes, [
    'POST /voice/v1/cards.list', 'POST /voice/v1/cards.balance', 'POST /voice/v1/statement.week.get',
    'POST /voice/v1/statement.week.decide', 'POST /voice/v1/statement.week.change',
    'POST /voice/v1/contact.email.get', 'POST /voice/v1/statement.pdf.send', 'POST /oauth2/token',
  ]);
  const pre = await call('OPTIONS', `${BASE}/cards.list`, undefined, { 'access-control-request-headers': 'authorization, content-type' });
  assert.equal(pre.status, 204);
  assert.equal(pre.res.headers.get('access-control-allow-headers'), 'authorization, content-type');
  const r = await post('cards.list', { customerNo: '90000001' });
  assert.equal(r.res.headers.get('access-control-allow-origin'), '*');
  assert.match(r.res.headers.get('content-type'), /application\/json/);
});

// ---------------------------------------------------------------- every entry of the file

assert.equal(settings.DELAY_SCALE, 1, 'deployed default: the real delay');
settings.DELAY_SCALE = 0.01; // 12 s -> 120 ms for the run

let entries = 0;
await test('every entry of test-customers.json: exact status and body', async () => {
  for (const c of SRC.customers) {
    const no = c.customerNo;
    for (const [s, v] of Object.entries(c.services)) {
      if (['cards.list', 'contact.email.get', 'statement.pdf.send'].includes(s)) {
        const data = { customerNo: no };
        if (s === 'cards.list') data.aiFlow = 'CardOps';
        if (s === 'contact.email.get') data.intAddressInfoType = 'E';
        if (s === 'statement.pdf.send') {
          const card = Object.keys(c.services['cards.balance'] ?? {})[0];
          Object.assign(data, {
            cardNumber: card ?? '', currencyType: 'TL', emailAddress: 'x@freyabank.example',
            statementDate: card ? c.services['cards.balance'][card].response.data?.statementDate ?? '' : '',
          });
        }
        exact(await post(s, data), v, `${no} ${s} (string)`);
        exact(await post(s, { ...data, customerNo: Number(no) }), v, `${no} ${s} (number)`);
        entries++;
      } else if (['cards.balance', 'statement.week.get'].includes(s)) {
        for (const [card, e] of Object.entries(v)) {
          const t0 = Date.now();
          exact(await post(s, { cardNumber: card }), e, `${no} ${s} ${card}`);
          if (e.delaySeconds) assert.ok(Date.now() - t0 >= e.delaySeconds * 1000 * settings.DELAY_SCALE - 5, 'delay honoured');
          entries++;
        }
      } else {
        for (const [card, weeks] of Object.entries(v)) {
          const day = c.services['statement.week.get'][card].response.data?.statementDay ?? 5;
          for (const [w, e] of Object.entries(weeks)) {
            exact(await post(s, { cardNumber: card, newStatementWeek: w, statementDay: day }), e, `${no} ${s} ${card} week "${w}"`);
            exact(await post(s, { cardNumber: card, newStatementWeek: Number(w), statementDay: day }), e, `${no} ${s} ${card} week ${w}`);
            entries++;
          }
        }
      }
    }
  }
  say(`   ${entries} entries, ${checks} exact answers`);
  assert.equal(entries, 617);
});

// ---------------------------------------------------------------- the delay entry

await test('delay entry (94907600 cards.balance 540000******7211, 12 s) waits, other calls do not wait for it', async () => {
  const e = svc('94907600', 'cards.balance')['540000******7211'];
  assert.equal(e.delaySeconds, 12);
  settings.DELAY_SCALE = 0.02; // 240 ms
  const t0 = Date.now();
  const order = [];
  const slow = post('cards.balance', { cardNumber: '540000******7211' }).then((r) => (order.push('slow'), r));
  const fast = post('statement.week.get', { cardNumber: '540000******7211' }).then((r) => (order.push('fast'), r));
  const same = post('contact.email.get', { customerNo: '94907600', intAddressInfoType: 'E' }).then((r) => (order.push('same'), r));
  const [rs, rf, rm] = await Promise.all([slow, fast, same]);
  assert.ok(Date.now() - t0 >= 235, 'waited');
  assert.equal(order[order.length - 1], 'slow');
  exact(rs, e, 'delayed');
  assert.ok(!('delaySeconds' in rs.data) && !rs.text.includes('delaySeconds'));
  exact(rf, svc('94907600', 'statement.week.get')['540000******7211'], 'concurrent week.get');
  exact(rm, svc('94907600', 'contact.email.get'), 'concurrent email');
  settings.DELAY_SCALE = 0.01;
});

// ---------------------------------------------------------------- leniency

await test('envelope: top-level fields without data, data as a JSON string, call/aiFlow/headers ignored', async () => {
  const want = svc('90000001', 'cards.list');
  exact(await call('POST', `${BASE}/cards.list`, { customerNo: '90000001' }), want, 'top level');
  exact(await call('POST', `${BASE}/cards.list`, { data: JSON.stringify({ customerNo: '90000001' }) }), want, 'data string');
  exact(await call('POST', `${BASE}/cards.list`, { data: { customerNo: '90000001', aiFlow: 'Other' }, call: { customerNo: '1' } }), want, 'call ignored');
  exact(await call('POST', `${BASE}/cards.list`, { data: { customerNo: '90000001' } }, { authorization: 'Bearer nonsense' }), want, 'any token');
  exact(await call('POST', `${BASE}/cards.list`, { data: { customerNo: '90000001' } }, { 'content-type': 'text/plain' }), want, 'any content type');
  // data wins over a top-level field of the same name
  exact(await call('POST', `${BASE}/cards.list`, { customerNo: '1', data: { customerNo: '90000001' } }), want, 'data wins');
});

await test('customerNo: string, number, spaces', async () => {
  const want = svc('92030487', 'cards.list');
  for (const v of ['92030487', 92030487, ' 92030487 ', '92030487\n']) exact(await post('cards.list', { customerNo: v }), want, `customerNo ${JSON.stringify(v)}`);
  exact(await post('contact.email.get', { customerNo: 90000001, intAddressInfoType: 'E' }), svc('90000001', 'contact.email.get'), 'email number');
  exact(await post('statement.pdf.send', { customerNo: ' 92460108 ' }), svc('92460108', 'statement.pdf.send'), 'pdf spaces');
  // alias spelling: served, with a warning in the log
  exact(await post('cards.list', { customerNumber: '92030487' }), want, 'alias');
  assert.match(lastLog().field_warning, /customerNo sent as customerNumber/);
});

await test('newStatementWeek: "3", 3, " 3 ", "03", 3.0 all the same entry', async () => {
  const card = '540000******1110';
  for (const s of ['statement.week.decide', 'statement.week.change']) {
    const want = svc('96158684', s)[card]['3'];
    for (const w of ['3', 3, ' 3 ', '03', 3.0, '3. hafta']) {
      exact(await post(s, { cardNumber: card, newStatementWeek: w, statementDay: 9 }), want, `${s} week ${JSON.stringify(w)}`);
    }
  }
});

await test('newStatementWeek as a word: üçüncü, "ikinci hafta", third, İLK... -> that week, with a warning', async () => {
  const forms = {
    1: ['bir', 'birinci', 'Birinci hafta', 'ilk', 'İLK HAFTA', 'first', 'one', 'the first week'],
    3: ['üç', 'üçüncü', 'ÜÇÜNCÜ', 'üçüncü hafta', 'üçüncü haftası', 'uc', 'third', 'three', 'the third week'],
    4: ['dört', 'dördüncü', 'dördüncü haftaya', 'fourth', 'four'],
  };
  for (const s of ['statement.week.decide', 'statement.week.change']) {
    const card = '540000******1110'; // 96158684, current week 2
    for (const [w, words] of Object.entries(forms)) {
      for (const word of words) {
        exact(await post(s, { cardNumber: card, newStatementWeek: word, statementDay: 9 }), svc('96158684', s)[card][w], `${s} ${JSON.stringify(word)}`);
        assert.match(lastLog().field_warning, new RegExp(`newStatementWeek sent as word .* -> ${w}\\)`), word);
      }
    }
    // 92220795's 3201 (current week 3): "ikinci" -> week 2, "üçüncü" -> its current week
    for (const word of ['ikinci', 'ikinci hafta', 'iki', 'second', 'two']) {
      exact(await post(s, { cardNumber: '540000******3201', newStatementWeek: word, statementDay: 16 }), svc('92220795', s)['540000******3201']['2'], `${s} 3201 ${word}`);
    }
    invalid(await post(s, { cardNumber: '540000******3201', newStatementWeek: 'üçüncü', statementDay: 16 }), /current statement week/);
    invalid(await post(s, { cardNumber: card, newStatementWeek: 'ikinci', statementDay: 9 }), /current statement week/);
    for (const word of ['beşinci', 'fifth', 'bir sonraki hafta', 'ikinci değil üçüncü', 'hafta', 'birkaç', 'constructor', 'toString', '__proto__']) {
      invalid(await post(s, { cardNumber: card, newStatementWeek: word, statementDay: 9 }), /must be 1, 2, 3 or 4/);
    }
  }
});

await test('card number leniency: full 16 digits, spaces, dashes, X/• masks, short masks, first4+last4, never last 4 alone', async () => {
  const bal = (card) => svc('90000001', 'cards.balance')[card];
  const want = bal('540000******1234');
  const forms = {
    '5400001234561234': 'first6+last4', '5400 0012 3456 1234': 'first6+last4', '5400-0012-3456-1234': 'first6+last4',
    '540000 ****** 1234': 'normalised', '5400 00** **** 1234': 'normalised', '540000XXXXXX1234': 'normalised',
    '540000xxxxxx1234': 'normalised', '540000••••••1234': 'normalised', '540000**1234': 'normalised',
    '540000*1234': 'normalised', ' 540000******1234 ': 'exact', '5400********1234': 'first4+last4',
    '5400 **** **** 1234': 'first4+last4',
  };
  for (const [form, how] of Object.entries(forms)) {
    exact(await post('cards.balance', { cardNumber: form }), want, `card ${form}`);
    if (how !== 'exact') assert.equal(lastLog().card_match, how, form);
  }
  exact(await post('cards.balance', { cardNumber: 5400001234561234 }), want, 'card as a JSON number');
  // the same resolution for every card service
  exact(await post('statement.week.get', { cardNumber: '5400********1234' }), svc('90000001', 'statement.week.get')['540000******1234'], 'week.get f4l4');
  exact(await post('statement.week.decide', { cardNumber: '5400********1234', newStatementWeek: 2, statementDay: 5 }),
    svc('90000001', 'statement.week.decide')['540000******1234']['2'], 'decide f4l4');
  // a made-up number that only ends like a card is not that card (seen: an agent invented 4543********1234)
  for (const made of ['1234', '****1234', '4543********1234', '4543210012341234']) {
    assert.equal((await post('cards.balance', { cardNumber: made })).status, 404, made);
  }
  exact(await post('statement.week.change', { cardNumber: '540000-XXXX-XX-1234', newStatementWeek: '4', statementDay: 5 }),
    svc('90000001', 'statement.week.change')['540000******1234']['4'], 'change dashes');
  // twin cards with the same last 4 stay apart by their first 6 (or first 4)
  exact(await post('cards.balance', { cardNumber: '545000******4253' }), svc('92030487', 'cards.balance')['545000******4253'], '545000 twin');
  exact(await post('cards.balance', { cardNumber: '5450********4253' }), svc('92030487', 'cards.balance')['545000******4253'], '5450 f4l4');
  exact(await post('cards.balance', { cardNumber: '5480001111114253' }), svc('94030575', 'cards.balance')['548000******4253'], 'full 548000');
  exact(await post('cards.balance', { cardNumber: '546000******3215' }), svc('93931069', 'cards.balance')['546000******3215'], '546000 twin');
});

await test('card number: ambiguous or unknown -> not found', async () => {
  const msg = 'Kart bakiye servisi hatası: kart bulunamadı';
  for (const v of ['4253', '****4253', '3215', '549000******4253', '5490********4253', '9999', '540000******9999', '12', 'abc']) {
    contractError(await post('cards.balance', { cardNumber: v }), 404, 'FB_IVR_CHANNEL_120', 'WARNING', msg);
  }
  assert.equal(lastLog().card_match, 'no_match');
  await post('cards.balance', { cardNumber: '4253' });
  assert.equal(lastLog().card_match, 'no_match');
  contractError(await post('statement.week.get', { cardNumber: '4253' }), 404, 'FB_IVR_CHANNEL_121', 'WARNING', /kart bulunamadı/);
  invalid(await post('statement.week.decide', { cardNumber: '4253', newStatementWeek: 2, statementDay: 5 }), /card not found/);
  invalid(await post('statement.week.change', { cardNumber: '540000******9999', newStatementWeek: 2, statementDay: 5 }), /card not found/);
});

// ---------------------------------------------------------------- not found

await test('not found: unknown customer, card, week; customers without a pdf entry', async () => {
  contractError(await post('cards.list', { customerNo: '12345678' }), 404, 'FB_IVR_CHANNEL_102', 'WARNING', 'Müşteriye ait geçerli kart bilgisi bulunamadı.');
  contractError(await post('statement.pdf.send', { customerNo: '12345678' }), 404, 'FB_IVR_CHANNEL_107', 'WARNING', 'Pdf dokümanı bulunamadı');
  invalid(await post('contact.email.get', { customerNo: '12345678', intAddressInfoType: 'E' }), /customer not found/);
  // the customers with no statement.pdf.send entry (all phone-only)
  const noPdf = SRC.customers.filter((c) => !c.services['statement.pdf.send']).map((c) => c.customerNo);
  assert.deepEqual(noPdf, ['93821776', '94907600', '96125950', '97631186', '97783309']);
  for (const no of noPdf) {
    contractError(await post('statement.pdf.send', { customerNo: no, cardNumber: '', currencyType: 'TL', statementDate: '05.10.2026', emailAddress: 'a@b.example' }),
      404, 'FB_IVR_CHANNEL_107', 'WARNING', 'Pdf dokümanı bulunamadı');
  }
  // the card's current week has no entry -> 400; so has a week outside 1-4
  for (const s of ['statement.week.decide', 'statement.week.change']) {
    invalid(await post(s, { cardNumber: '540000******1110', newStatementWeek: '2', statementDay: 9 }), /current statement week/);
    invalid(await post(s, { cardNumber: '540000******1110', newStatementWeek: 5, statementDay: 9 }), /must be 1, 2, 3 or 4/);
    invalid(await post(s, { cardNumber: '540000******1110', newStatementWeek: 'abc', statementDay: 9 }), /must be 1, 2, 3 or 4/);
    invalid(await post(s, { cardNumber: '540000******1110', newStatementWeek: 0, statementDay: 9 }), /must be 1, 2, 3 or 4/);
  }
  // guids differ per error
  const a = await post('cards.list', { customerNo: '1' });
  const b = await post('cards.list', { customerNo: '1' });
  assert.notEqual(a.data.result.guid, b.data.result.guid);
});

// ---------------------------------------------------------------- missing fields

await test('missing or empty required fields -> 400 INVALID_ARGUMENTS_ERROR naming the field', async () => {
  for (const empty of [undefined, '', '   ', null]) {
    const v = (x) => (empty === undefined ? {} : { [x]: empty });
    invalid(await post('cards.list', { ...v('customerNo'), aiFlow: 'CardOps' }), 'customer number cannot be empty');
    invalid(await post('cards.balance', v('cardNumber')), 'card number cannot be empty');
    invalid(await post('statement.week.get', v('cardNumber')), 'card number cannot be empty');
    for (const s of ['statement.week.decide', 'statement.week.change']) {
      invalid(await post(s, { ...v('cardNumber'), newStatementWeek: 2, statementDay: 5 }), 'card number cannot be empty');
      invalid(await post(s, { cardNumber: '540000******1234', ...v('newStatementWeek'), statementDay: 5 }), 'newStatementWeek cannot be empty');
    }
    invalid(await post('contact.email.get', { ...v('customerNo'), intAddressInfoType: 'E' }), 'customer number cannot be empty');
    invalid(await post('statement.pdf.send', { ...v('customerNo'), cardNumber: '540000******1234' }), 'customer number cannot be empty');
  }
  invalid(await post('contact.email.get', { customerNo: '90000001', intAddressInfoType: '' }), 'intAddressInfoType cannot be empty');
  invalid(await post('contact.email.get', { customerNo: '90000001', intAddressInfoType: null }), 'intAddressInfoType cannot be empty');
  invalid(await call('POST', `${BASE}/cards.list`, {}), 'customer number cannot be empty');
  invalid(await call('POST', `${BASE}/cards.list`, ''), 'customer number cannot be empty');
});

await test('lenient optional fields: served, with a warning in the log', async () => {
  const email = svc('90000001', 'contact.email.get');
  exact(await post('contact.email.get', { customerNo: '90000001' }), email, 'no intAddressInfoType');
  assert.match(lastLog().field_warning, /intAddressInfoType missing/);
  for (const t of ['E', 'P', 'B', 'X']) exact(await post('contact.email.get', { customerNo: '90000001', intAddressInfoType: t }), email, `type ${t}`);
  exact(await post('statement.week.decide', { cardNumber: '540000******1234', newStatementWeek: 2 }),
    svc('90000001', 'statement.week.decide')['540000******1234']['2'], 'no statementDay');
  assert.match(lastLog().field_warning, /statementDay missing/);
  exact(await post('statement.week.change', { cardNumber: '540000******1234', newStatementWeek: 2, statementDay: 9 }),
    svc('90000001', 'statement.week.change')['540000******1234']['2'], 'other statementDay');
  assert.match(lastLog().field_warning, /statementDay 9, the card's is 5/);
  exact(await post('statement.pdf.send', { customerNo: '90000001' }), svc('90000001', 'statement.pdf.send'), 'pdf customer only');
  assert.match(lastLog().field_warning, /cardNumber missing; currencyType missing; statementDate missing; emailAddress missing/);
  exact(await post('statement.pdf.send', {
    customerNo: '90000001', cardNumber: '540000******1110', currencyType: 'TRY', statementDate: '05.09.2026', emailAddress: 'other@x.example',
  }), svc('90000001', 'statement.pdf.send'), 'pdf other fields');
  const w = lastLog().field_warning;
  for (const re of [/not this customer's/, /not the registered/, /issued statement is 09.10.2026/, /not TL\/USD\/EUR\/GBP/]) assert.match(w, re);
});

// ---------------------------------------------------------------- template variables

await test('template variables ({{...}} or %7B%7B...) are unknown values: the service\'s 404/400, template_warning in the log', async () => {
  const t = '{{customerNumber}}';
  const listMsg = 'Müşteriye ait geçerli kart bilgisi bulunamadı.';
  contractError(await post('cards.list', { customerNo: t, aiFlow: 'CardOps' }), 404, 'FB_IVR_CHANNEL_102', 'WARNING', listMsg);
  assert.equal(lastLog().template_warning, 'unfilled placeholder in customerNo');
  assert.equal(lastLog().matched, undefined);
  contractError(await post('cards.list', { customerNo: '%7B%7BcustomerNumber%7D%7D' }), 404, 'FB_IVR_CHANNEL_102', 'WARNING', listMsg);
  contractError(await post('cards.list', { customerNo: '9000{{x}}0001' }), 404, 'FB_IVR_CHANNEL_102', 'WARNING', listMsg);
  invalid(await post('contact.email.get', { customerNo: t, intAddressInfoType: '{{type}}' }), /customer not found/);
  assert.equal(lastLog().template_warning, 'unfilled placeholder in customerNo, intAddressInfoType');
  contractError(await post('statement.pdf.send', { customerNo: t, cardNumber: '{{cardNumber}}', currencyType: '{{c}}', statementDate: '{{d}}', emailAddress: '{{e}}' }),
    404, 'FB_IVR_CHANNEL_107', 'WARNING', 'Pdf dokümanı bulunamadı');
  for (const card of ['{{selectedCard}}', '%7B%7BselectedCard%7D%7D', '{{card1234}}', '540000******{{last4}}']) {
    contractError(await post('cards.balance', { cardNumber: card }), 404, 'FB_IVR_CHANNEL_120', 'WARNING', /kart bulunamadı/);
    assert.equal(lastLog().card_match, 'template');
    contractError(await post('statement.week.get', { cardNumber: card }), 404, 'FB_IVR_CHANNEL_121', 'WARNING', /kart bulunamadı/);
  }
  for (const s of ['statement.week.decide', 'statement.week.change']) {
    invalid(await post(s, { cardNumber: '{{card}}', newStatementWeek: '{{week}}', statementDay: '{{day}}' }), /card not found/);
    invalid(await post(s, { cardNumber: '{{card}}', newStatementWeek: 3, statementDay: 5 }), /card not found/);
    for (const w of ['{{week}}', '{{week2}}', '%7B%7Bweek%7D%7D']) {
      invalid(await post(s, { cardNumber: '540000******1234', newStatementWeek: w, statementDay: 5 }), /must be 1, 2, 3 or 4/);
    }
    assert.match(lastLog().template_warning, /newStatementWeek/);
  }
  // the compiled tools' panel defaults ({"call":"{{call}}","data":"{{data}}"}): 400 naming the field
  for (const s of ['cards.list', 'contact.email.get', 'statement.pdf.send']) {
    invalid(await call('POST', `${BASE}/${s}`, { call: '{{call}}', data: '{{data}}' }), 'customer number cannot be empty');
  }
  for (const s of ['cards.balance', 'statement.week.get', 'statement.week.decide', 'statement.week.change']) {
    invalid(await call('POST', `${BASE}/${s}`, { call: '{{call}}', data: '{{data}}' }), 'card number cannot be empty');
  }
  // a variable written without quotes arrives as invalid JSON: quoted, then refused like any unknown value
  invalid(await call('POST', `${BASE}/contact.email.get`, '{"data": {"customerNo": {{customerNumber}}, "intAddressInfoType": "E"}, "call": {"ani": "{{ani}}"}}'),
    /customer not found/);
  invalid(await call('POST', `${BASE}/statement.week.decide`, '{"data": {"cardNumber": "{{card}}", "newStatementWeek": {{week}}, "statementDay": {{day}}}}'),
    /card not found/);
});

// ---------------------------------------------------------------- paths, token, bad requests

await test('paths: without /voice/v1, trailing slash; unknown path 404; GET 405; bad JSON 400', async () => {
  exact(await call('POST', '/cards.list', { data: { customerNo: '90000001' } }), svc('90000001', 'cards.list'), 'no prefix');
  exact(await call('POST', `${BASE}/cards.list/`, { data: { customerNo: '90000001' } }), svc('90000001', 'cards.list'), 'trailing slash');
  exact(await call('POST', '/statement.week.get', { data: { cardNumber: '540000******3201' } }),
    svc('92220795', 'statement.week.get')['540000******3201'], 'no prefix week.get');
  contractError(await call('POST', `${BASE}/cards.lists`, { data: {} }), 404, 'NOT_FOUND', 'ERROR', /no route for POST \/voice\/v1\/cards\.lists/);
  contractError(await call('POST', '/v1/cards.list', { data: { customerNo: '90000001' } }), 404, 'NOT_FOUND', 'ERROR', /routes: POST \/voice\/v1\/cards\.list/);
  contractError(await call('GET', `${BASE}/cards.list`), 405, 'METHOD_NOT_ALLOWED', 'ERROR', /use POST/);
  invalid(await call('POST', `${BASE}/cards.list`, '{"data": {"customerNo": }'), /not valid JSON/);
  invalid(await call('POST', `${BASE}/cards.list`, '{"data": {"customerNo": "90000001"'), /not valid JSON/);
});

await test('token: form or JSON, same answer, nothing checked', async () => {
  const want = { access_token: 'test-token', token_type: 'Bearer', expires_in: 1800 };
  const form = await call('POST', '/oauth2/token', 'grant_type=client_credentials&client_id=a&client_secret=b&scope=voice.statement',
    { 'content-type': 'application/x-www-form-urlencoded' });
  assert.equal(form.status, 200);
  assert.equal(form.text, JSON.stringify(want));
  for (const [body, h] of [[{ grant_type: 'client_credentials' }, {}], ['grant_type=client_credentials', {}], ['', {}]]) {
    const r = await call('POST', '/oauth2/token', body, h);
    assert.equal(r.status, 200);
    assert.deepEqual(r.data, want);
  }
  assert.deepEqual((await call('POST', `${BASE}/oauth2/token`, {})).data, want);
});

// ---------------------------------------------------------------- statelessness and observation

await test('stateless: a week change or a pdf send changes no answer; recorded for /__state only', async () => {
  await call('POST', '/__reset');
  const card = '540000******1110';
  const get = svc('96158684', 'statement.week.get')[card];
  const chg = svc('96158684', 'statement.week.change')[card]['3'];
  exact(await post('statement.week.change', { cardNumber: card, newStatementWeek: 3, statementDay: 9 }), chg, 'change 1');
  exact(await post('statement.week.change', { cardNumber: card, newStatementWeek: 3, statementDay: 9 }), chg, 'change 2 (same answer)');
  exact(await post('statement.week.get', { cardNumber: card }), get, 'week unchanged');
  exact(await post('statement.week.decide', { cardNumber: card, newStatementWeek: 3, statementDay: 9 }),
    svc('96158684', 'statement.week.decide')[card]['3'], 'decide unchanged');
  invalid(await post('statement.week.decide', { cardNumber: card, newStatementWeek: 2, statementDay: 9 }), /current statement week/);
  exact(await post('statement.pdf.send', { customerNo: '96158684', cardNumber: card, currencyType: 'TL', statementDate: '09.10.2026', emailAddress: 'kerem.aksoy@freyabank.example' }),
    svc('96158684', 'statement.pdf.send'), 'pdf 1');
  exact(await post('statement.pdf.send', { customerNo: '96158684', cardNumber: card, currencyType: 'TL', statementDate: '09.10.2026', emailAddress: 'kerem.aksoy@freyabank.example' }),
    svc('96158684', 'statement.pdf.send'), 'pdf 2');
  assert.equal(lastLog().field_warning, undefined);
  const st = (await call('GET', '/__state')).data;
  assert.equal(st.records['96158684'].week_change.length, 2);
  assert.equal(st.records['96158684'].pdf_send.length, 2);
  assert.equal(st.records['96158684'].week_change[0].newStatementWeek, '3');
  const log = (await call('GET', '/__log?limit=3')).data;
  assert.equal(log.entries.length, 3);
  assert.equal(log.entries[2].path, '/voice/v1/statement.pdf.send');
  assert.deepEqual(log.entries[2].matched, { customerNo: '96158684' });
  await call('POST', '/__reset');
  assert.deepEqual((await call('GET', '/__state')).data.records, {});
  assert.equal((await call('GET', '/__log')).data.count, 0);
});

// ---------------------------------------------------------------- durable object

class FakeStorage {
  constructor() { this.data = new Map(); this.writes = 0; }
  async get(keys) {
    const one = (k) => structuredClone(this.data.get(k));
    return Array.isArray(keys) ? new Map(keys.filter((k) => this.data.has(k)).map((k) => [k, one(k)])) : one(keys);
  }
  async put(entries) {
    for (const [k, v] of Object.entries(entries)) this.data.set(k, structuredClone(v));
    this.writes++;
  }
}
const fakeEnv = (storage) => {
  const instance = new MockState({ storage, blockConcurrencyWhile: (fn) => fn() }, {});
  return { MOCK: { idFromName: (name) => name, get: () => instance } };
};

await test('durable object: same answers, records and log saved and restored', async () => {
  const storage = new FakeStorage();
  const env = fakeEnv(storage);
  assert.equal((await call('GET', '/__health', undefined, {}, env)).data.store, 'durable_object');
  const card = '540000******2000';
  const chg = svc('95004361', 'statement.week.change')[card]['2'];
  exact(await call('POST', `${BASE}/statement.week.change`, { data: { cardNumber: card, newStatementWeek: 2, statementDay: 5 } }, {}, env), chg, 'via DO');
  exact(await call('POST', `${BASE}/cards.balance`, { data: { cardNumber: '540000******7211' } }, {}, env),
    svc('94907600', 'cards.balance')['540000******7211'], 'delayed via DO');
  await call('POST', '/__reset'); // in-process memory only
  const env2 = fakeEnv(storage); // restart from the same storage
  const st = (await call('GET', '/__state', undefined, {}, env2)).data;
  assert.equal(st.records['95004361'].week_change.length, 1);
  assert.equal((await call('GET', '/__log', undefined, {}, env2)).data.count, 2);
  exact(await call('POST', `${BASE}/statement.week.change`, { data: { cardNumber: card, newStatementWeek: 2, statementDay: 5 } }, {}, env2), chg, 'again via DO');
  await call('POST', '/__reset', undefined, {}, env2);
  assert.equal((await call('GET', '/__state', undefined, {}, fakeEnv(storage))).data.count, 0);
});

// ---------------------------------------------------------------- example-scenarios.md

await test('example-scenarios.md: the answers the six examples rely on', async () => {
  const bal = async (card) => (await post('cards.balance', { cardNumber: card })).data.data;
  const list = async (no) => (await post('cards.list', { customerNo: no })).data.data;
  const pick = (b) => [b.statementDebt, b.minPayment, b.remainingDebt, b.remainingMinPayment, b.totalDebt];

  // 1. 95004361: one card 2000 Yıldız Premium, statement 05.10.2026, TL 12000/4800, remaining 9500/2000,
  //    EUR 85.20/34.10, USD and GBP no debt, due 15.10.2026
  let l = await list('95004361');
  assert.deepEqual(l.cards.map((c) => [c.cardNumberLast4, c.productName]), [['2000', 'Yıldız Premium']]);
  let b = await bal(l.cards[0].cardNumber);
  assert.deepEqual([b.statementDate, b.lastPayDate], ['05.10.2026', '15.10.2026']);
  assert.deepEqual(pick(b.debtTL), [12000, 4800, 9500, 2000, 9500]);
  assert.deepEqual([b.debtEUR.statementDebt, b.debtEUR.minPayment], [85.2, 34.1]);
  assert.deepEqual([b.debtUSD.statementPaymentStatus, b.debtGBP.statementPaymentStatus], ['NO_DEBT', 'NO_DEBT']);

  // 2./5. 96158684: card 1110, TL 10000, remaining 5000, minimum paid, due 19.10.2026; week 2,
  //    next 09.11.2026 / 19.11.2026; week 3 preview 16.11.2026 / 26.11.2026; change OK
  l = await list('96158684');
  assert.deepEqual(l.cards.map((c) => c.cardNumber), ['540000******1110']);
  b = await bal('540000******1110');
  assert.deepEqual([b.debtTL.statementDebt, b.debtTL.remainingDebt, b.debtTL.remainingMinPayment, b.lastPayDate], [10000, 5000, 0, '19.10.2026']);
  assert.equal(b.debtGBP, undefined); // no GBP block on this card
  const wk = (await post('statement.week.get', { cardNumber: '540000******1110' })).data.data;
  assert.deepEqual([wk.statementWeek, wk.statementDay, wk.nextStatementDate, wk.nextLastPayDate], [2, 9, '09.11.2026', '19.11.2026']);
  const dec = (await post('statement.week.decide', { cardNumber: '540000******1110', newStatementWeek: 3, statementDay: 9 })).data.data;
  assert.deepEqual([dec.statementDate, dec.statementDueDate], ['16.11.2026', '26.11.2026']);
  const ch = (await post('statement.week.change', { cardNumber: '540000******1110', newStatementWeek: 3, statementDay: 9 })).data.data;
  assert.deepEqual([ch.exitState, ch.responseCode, ch.statementWeek], ['OK', 0, '3']);
  for (const w of [1, 4]) assert.equal((await post('statement.week.decide', { cardNumber: '540000******1110', newStatementWeek: w, statementDay: 9 })).status, 200);

  // 3. 97526380: three cards; Yıldız Premium 22500 / 9000, due 15.10.2026
  l = await list('97526380');
  assert.deepEqual(l.cards.map((c) => c.productName), ['Yıldız Premium', 'Yıldız Fly', 'Yıldız Platinum']);
  assert.equal(l.exitState, 'MULTI_CARD');
  b = await bal(l.cards.find((c) => c.productName === 'Yıldız Premium').cardNumber);
  assert.deepEqual([b.debtTL.statementDebt, b.debtTL.minPayment, b.lastPayDate], [22500, 9000, '15.10.2026']);

  // 4. 92460108: TL 18500/7400, USD 650/260, EUR 380/152, GBP none, due 15.10.2026,
  //    e-mail ece.demir@freyabank.example, pdf DONE
  b = await bal('540000******8500');
  assert.deepEqual([b.debtTL, b.debtUSD, b.debtEUR].map((x) => [x.statementDebt, x.minPayment]), [[18500, 7400], [650, 260], [380, 152]]);
  assert.deepEqual([b.debtGBP.statementPaymentStatus, b.lastPayDate], ['NO_DEBT', '15.10.2026']);
  const em = (await post('contact.email.get', { customerNo: '92460108', intAddressInfoType: 'E' })).data.data;
  assert.equal(em.ibanEmail, 'ece.demir@freyabank.example');
  const pdf = await post('statement.pdf.send', { customerNo: '92460108', cardNumber: '540000******8500', currencyType: 'TL', statementDate: '05.10.2026', emailAddress: em.ibanEmail });
  assert.deepEqual([pdf.status, pdf.data.data.exitState], [200, 'DONE']);

  // 6. 96125950: card 7200 Yıldız Premium, statement 09.10.2026, 7200 / 2880, no USD/EUR/GBP debt,
  //    due 19.10.2026, no registered e-mail
  l = await list('96125950');
  assert.deepEqual(l.cards.map((c) => [c.cardNumberLast4, c.productName]), [['7200', 'Yıldız Premium']]);
  b = await bal('540000******7200');
  assert.deepEqual([b.statementDate, b.debtTL.statementDebt, b.debtTL.minPayment, b.lastPayDate], ['09.10.2026', 7200, 2880, '19.10.2026']);
  assert.deepEqual([b.debtUSD, b.debtEUR, b.debtGBP].map((x) => x.statementPaymentStatus), ['NO_DEBT', 'NO_DEBT', 'NO_DEBT']);
  const em6 = (await post('contact.email.get', { customerNo: '96125950', intAddressInfoType: 'E' })).data.data;
  assert.deepEqual([em6.communicationType, em6.ibanEmail], ['Phone', '']);
});

say(`\n${n} tests passed, ${checks} answers checked (${entries} file entries, each sent in every accepted form)`);
