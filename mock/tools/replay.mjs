// Replays the tool calls of sample conversations against the mock and diffs the results.
//
//   node mock/tools/replay.mjs <dir or .md files...> [--call tool,araç] [--result result,sonuç]
//        [--url https://<mock>/v1] [--reset] [--ignore mesaj,created_at,...]
//        [--header 'X-Kanal: sesli-asistan' ...]
//
// A call is a line '[<call word>: <operation> {json body}]' (POST <base>/<operation>) or
// '[<call word>: GET /a/b?x=1]' / '[<call word>: POST /a/b {json}]' (method and path, REST style;
// a path that already starts with the base is not prefixed again). GET sends no body: a JSON
// body given with it becomes the query. Its expected result is the next non-empty line:
//   '[<result word>: {json}]'        body must match, status any 2xx;
//   '[<result word>: 201 {json}]'    status (also 'HTTP 201 {json}') must match too;
//   '[<result word>: 404]' or a text naming 'HTTP 404'   status only.
// --header (repeatable) adds a request header to every call.
// Without --url it runs the local worker (../src), resetting its state before each file
// (one file = one simulation); with --url it calls that mock, and resets it only with --reset.
// Generated record numbers are not compared: a key id/no or ending in _id/_no/Id/No that no request
// in the files sends only needs a value of the same type (non-empty for text). A key that a
// request sends (ekstre_no sent back to the mock, customer_id) is compared exactly. --ignore
// keys (a server message text, a timestamp) are always compared that loosely. The last lines
// list which keys were loose. Exit code 1 when anything differs.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const args = process.argv.slice(2);
const opt = (name, dflt) => {
  const i = args.indexOf(`--${name}`);
  return i < 0 ? dflt : args.splice(i, 2)[1];
};
const flag = (name) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 && args.splice(i, 1).length > 0;
};
const words = (s) => s.split(',').map((w) => w.trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
const METHOD = '(?:(GET|POST|PUT|PATCH|DELETE|get|post|put|patch|delete)\\s+)?';
const callRe = new RegExp(`^\\s*\\[(?:${words(opt('call', 'tool,araç,call'))}):\\s*${METHOD}([\\p{L}\\p{N}_./%{}?=&~+-]+)\\s*(\\{.*\\})?\\s*\\]\\s*$`, 'u');
const resultRe = new RegExp(`^\\s*\\[(?:${words(opt('result', 'result,sonuç'))}):\\s*(.*?)\\s*\\]?\\s*$`, 'u');
const url = opt('url', null)?.replace(/\/+$/, '');
const ignore = new Set(opt('ignore', '').split(',').map((k) => k.trim()).filter(Boolean));
const headers = {};
for (let h; (h = opt('header', null)) !== null;) {
  const i = typeof h === 'string' ? h.indexOf(':') : -1;
  if (i < 1) {
    console.error(`--header needs 'Name: value', got '${h}'`);
    process.exit(2);
  }
  headers[h.slice(0, i).trim().toLowerCase()] = h.slice(i + 1).trim();
}
const reset = flag('reset') || !url;
if (!args.length) {
  console.error('usage: node replay.mjs <dir or .md files...> [--call w1,w2] [--result w1,w2] [--url base] [--reset]'
    + " [--ignore k1,k2] [--header 'Name: value' ...]");
  process.exit(2);
}

const here = path.dirname(fileURLToPath(import.meta.url));
let send, base;
if (url) {
  base = new URL(url).pathname.replace(/\/+$/, '');
  send = (method, p, body) => fetch(new URL(url).origin + p, init(method, body));
} else {
  const worker = (await import(path.join(here, '../src/worker.js'))).default;
  base = (await import(path.join(here, '../src/routes.js'))).BASE ?? '';
  console.log = () => {}; // the worker's request lines
  send = (method, p, body) => worker.fetch(new Request(`https://mock.test${p}`, init(method, body)));
}
function init(method, body) {
  return { method, headers: { 'content-type': 'application/json', ...headers }, ...(body !== undefined && { body }) };
}
// The call's path: base + operation, unless it already starts with the base.
function target(op) {
  const p = `/${op.replace(/^\/+/, '')}`;
  return base && (p === base || p.startsWith(`${base}/`) || p.startsWith(`${base}?`)) ? p : base + p;
}

// One call line: method, path (GET: body as query), body text, and the request's field names.
function parseCall(m) {
  const [, verb, op, json] = m;
  const method = (verb ?? 'POST').toUpperCase();
  let p = target(op), body = json, keys = [];
  let obj;
  try { obj = json ? JSON.parse(json) : undefined; } catch { obj = undefined; }
  if (obj && typeof obj === 'object' && !Array.isArray(obj)) keys = Object.keys(obj);
  if (method === 'GET') {
    if (obj && typeof obj === 'object' && keys.length) p += (p.includes('?') ? '&' : '?') + new URLSearchParams(obj);
    body = undefined;
  } else body ??= '{}';
  const q = p.indexOf('?');
  if (q >= 0) keys.push(...new URLSearchParams(p.slice(q + 1)).keys());
  return { method, p, body, keys };
}

const files = args.flatMap((a) => (fs.statSync(a).isDirectory()
  ? fs.readdirSync(a).filter((f) => f.endsWith('.md')).sort().map((f) => path.join(a, f)) : [a]));
const texts = new Map(files.map((f) => [f, fs.readFileSync(f, 'utf8').split('\n')]));

// Field names any request sends: a record-number key among them is compared exactly.
const sent = new Set();
for (const lines of texts.values()) {
  for (const l of lines) {
    const m = callRe.exec(l);
    if (m) for (const k of parseCall(m).keys) sent.add(k);
  }
}
const recordNo = (key) => /(?:^id|^no|_id|_no|Id|ID|No)$/.test(key); // id, promise_id, kayit_no, caseId
const loose = new Set();

// Expected and got are the same, key order aside; record numbers and --ignore keys only need
// a value of the same type (non-empty text).
function same(want, got, key = '') {
  if (key && want != null && typeof want !== 'object' && (ignore.has(key) || (recordNo(key) && !sent.has(key)))) {
    loose.add(key);
    return typeof got === typeof want && (typeof got !== 'string' || got !== '');
  }
  if (Array.isArray(want)) return Array.isArray(got) && want.length === got.length && want.every((w, i) => same(w, got[i]));
  if (want && typeof want === 'object') {
    if (!got || typeof got !== 'object' || Array.isArray(got)) return false;
    const keys = new Set([...Object.keys(want), ...Object.keys(got)]);
    return [...keys].every((k) => same(want[k], got[k], k));
  }
  return want === got;
}

// Expected result text against the response.
function check(want, status, got) {
  const st = /^(?:HTTP\s*)?(\d{3})(?!\d)\s*(.*)$/is.exec(want); // '201 {json}', 'HTTP 404', '404'
  const parse = (s) => {
    try { return { value: JSON.parse(s) }; } catch { return null; }
  };
  if (st) {
    const rest = st[2].trim();
    const body = rest ? parse(rest) : null;
    if (!body && /^[[{]/.test(rest)) return false; // a body that is not valid JSON: shown, not skipped
    return Number(st[1]) === status && (!body || same(body.value, got));
  }
  const body = parse(want);
  if (body) return same(body.value, got) && status < 300;
  const code = /HTTP\s*(\d{3})/i.exec(want);
  return Boolean(code) && Number(code[1]) === status;
}

const out = (...s) => process.stdout.write(s.join(' ') + '\n');
let total = 0, diffs = 0;
for (const [file, lines] of texts) {
  if (reset) await send('POST', '/__reset');
  for (let i = 0; i < lines.length; i++) {
    const m = callRe.exec(lines[i]);
    if (!m) continue;
    const { method, p, body } = parseCall(m);
    const res = await send(method, p, body);
    const text = await res.text();
    let got;
    try { got = JSON.parse(text); } catch { got = text; }
    let j = i + 1;
    while (j < lines.length && !lines[j].trim()) j++;
    const r = resultRe.exec(lines[j] ?? '');
    const what = [path.basename(file), method, p, body ?? ''].join(' ');
    if (!r || callRe.test(lines[j])) {
      out('call', what, '->', res.status, text);
      continue;
    }
    total++;
    const ok = check(r[1], res.status, got);
    if (!ok) diffs++;
    out(ok ? 'same' : 'DIFF', what);
    if (!ok) out('   want', r[1], '\n   got ', res.status, text);
  }
}
out(`${total - diffs}/${total} results the same${diffs ? `, ${diffs} differ` : ''}`);
if (loose.size) out(`not compared exactly (record numbers / --ignore): ${[...loose].sort().join(', ')}`);
const exact = [...sent].filter(recordNo).filter((k) => !ignore.has(k));
if (exact.length) out(`record-number keys compared exactly (sent in a request): ${exact.sort().join(', ')}`);
process.exitCode = diffs ? 1 : 0;
