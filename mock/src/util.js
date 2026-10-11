// Generic helpers for handlers: JSON responses, Turkish-aware matching, dates, times, amounts,
// enums, lookup, required fields.

// json(data) is HTTP 200; a contract that answers 201 (or 202, 204...) needs json(data, 201).
export function json(data, status = 200, headers = {}) {
  return new Response(JSON.stringify(data ?? null), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8', ...headers },
  });
}

// The error body every helper here and the worker's own errors (bad JSON 400, 405, unknown path
// 404, 500, missing header) are built with: (status, code, extra) => body. extra.message is a
// human-readable text when there is one. The default is { ok: false, error: code, ...extra };
// routes.js may export errorBody(status, code, extra) for the contract's shape, which worker.js
// installs with setErrorBody.
export const defaultErrorBody = (status, code, extra = {}) => ({ ok: false, error: code, ...extra });
let buildError = defaultErrorBody;
export function setErrorBody(fn) {
  buildError = typeof fn === 'function' ? fn : defaultErrorBody;
}
// The body the current builder makes (a throwing builder falls back to the default shape).
export function errorBodyOf(status, code, extra = {}) {
  const x = typeof extra === 'string' ? { message: extra } : extra ?? {};
  try {
    return buildError(status, code, x);
  } catch (e) {
    return { ...defaultErrorBody(status, code, x), error_body_failed: String(e?.message ?? e) };
  }
}

// error(422, 'code'), error(422, 'code', { field: 'x' }), error(422, 'code', 'message text').
export const error = (status, code, extra = {}, headers = {}) =>
  json(errorBodyOf(status, code, extra), status, headers);

// A refusal the contract puts under HTTP 200: { ok: false, error: code, ...extra } by default.
export const refuse = (code, extra = {}) => json(errorBodyOf(200, code, extra));

// Only the listed fields, for answering with the contract's fields and not the internal ones
// (recordOnce's replayed, session, kind, at...): pick(entry, ['amount', 'date']), or with
// renames and dotted paths: pick(entry, { promise_no: 'id', amount: 'amount', due: 'plan.date' }).
// Missing fields are left out.
export function pick(obj, fields) {
  const pairs = Array.isArray(fields) ? fields.map((f) => [f, f]) : Object.entries(fields ?? {});
  return Object.fromEntries(pairs.map(([out, src]) => [out, get(obj ?? {}, src)]).filter(([, v]) => v !== undefined));
}

// Trim, collapse spaces, Turkish-aware lowercase (I -> ı, İ -> i).
export const norm = (s) =>
  String(s ?? '').trim().replace(/\s+/g, ' ').replace(/I/g, 'ı').replace(/İ/g, 'i').toLowerCase();

// norm() without Turkish diacritics, so "AYSE ISIK" matches "Ayşe Işık".
const FOLD = { ç: 'c', ğ: 'g', ı: 'i', ö: 'o', ş: 's', ü: 'u', â: 'a', î: 'i', û: 'u' };
export const fold = (s) => norm(s).replace(/[çğıöşüâîû]/g, (c) => FOLD[c]);
export const sameText = (a, b) => fold(a) === fold(b);

export const digits = (s) => String(s ?? '').replace(/\D/g, '');

// Same digits; with n, only the last n digits count (last-4, phone with or without +90/0).
export function sameDigits(a, b, n) {
  let x = digits(a), y = digits(b);
  if (n) {
    if (x.length < n || y.length < n) return false;
    x = x.slice(-n);
    y = y.slice(-n);
  }
  return x !== '' && x === y;
}
export const samePhone = (a, b) => sameDigits(a, b, 10);

// Month by its first three folded letters, Turkish or English.
const MONTHS = ['oca jan', 'sub feb', 'mar', 'nis apr', 'may', 'haz jun',
  'tem jul', 'agu aug', 'eyl sep', 'eki oct', 'kas nov', 'ara dec'];
const month = (name) => MONTHS.findIndex((m) => m.split(' ').includes(fold(name).slice(0, 3))) + 1;

// 'YYYY-MM-DD' from 'YYYY-MM-DD[T..]', 'DD.MM.YYYY', 'DD/MM/YYYY', '5 Ekim 2026', '5 October 2026';
// null when it is not a real date.
export function isoDate(s) {
  const t = String(s ?? '').trim();
  let r, y, m, d;
  if ((r = /^(\d{4})-(\d{1,2})-(\d{1,2})/.exec(t))) [, y, m, d] = r;
  else if ((r = /^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$/.exec(t))) [, d, m, y] = r;
  else if ((r = /^(\d{1,2})\.?\s+(\p{L}+)\s+(\d{4})$/u.exec(t))) [d, m, y] = [r[1], month(r[2]), r[3]];
  else return null;
  const dt = new Date(Date.UTC(+y, +m - 1, +d));
  if (!+m || dt.getUTCMonth() !== +m - 1 || dt.getUTCDate() !== +d) return null;
  return dt.toISOString().slice(0, 10);
}
export const sameDate = (a, b) => isoDate(a) !== null && isoDate(a) === isoDate(b);

// 'DD.MM.YYYY' (or with another separator) for anything isoDate reads, for contracts that answer
// in that format: toDMY('2026-10-30') -> '30.10.2026'. Not a date (null, '', text): returned as is.
export function toDMY(v, sep = '.') {
  const iso = isoDate(v);
  return iso ? iso.split('-').reverse().join(sep) : v;
}

// 'YYYY-MM-DD HH:MM' from a date and a time: '2026-10-22 19:30', '22.10.2026 19:30',
// '2026-10-22T19:30', '2026-10-22T19:30:00+03:00' (the time as written; seconds and offset
// dropped), '22.10.2026, 19.30', '22 Ekim 2026 saat 19:30'. null when either part is unreadable
// or missing. Another format: parseDateTime(v)?.replace(' ', 'T').
export function parseDateTime(v) {
  const m = /^(.*?)(?:[\s,]+|T)(?:[Ss]aat\s*)?(\d{1,2})[:.](\d{2})(?::\d{2}(?:\.\d+)?)?\s*(?:Z|[+-]\d{2}:?\d{2})?$/u
    .exec(String(v ?? '').trim());
  const d = m && isoDate(m[1].replace(/[\s,]+$/, ''));
  const t = m && hhmm(`${m[2]}:${m[3]}`);
  return d && t ? `${d} ${t}` : null;
}

// True when answer is truth with day and month swapped ('1981-11-08' for '1981-08-11').
export function dayMonthSwapped(answer, truth) {
  const a = isoDate(answer), t = isoDate(truth);
  return a !== null && t !== null && a !== t && `${a.slice(0, 4)}-${a.slice(8, 10)}-${a.slice(5, 7)}` === t;
}

// 'HH:MM' from '11:00', '11.00', '11', '9:30', 'saat 11:30', '2026-10-15T11:00'; null otherwise.
export function hhmm(v) {
  const m = /(\d{1,2})(?:\s*[:.]\s*(\d{2}))?/.exec(String(v ?? '').replace(/^.*T/, ''));
  if (!m || +m[1] > 23 || +(m[2] ?? 0) > 59) return null;
  return `${m[1].padStart(2, '0')}:${m[2] ?? '00'}`;
}

// Number from 1250, '1250.50', '1.250,50', '1.250,50 TL', '₺1.250'; null if not an amount.
// A single comma is a decimal comma (Turkish); dots in groups of three are thousands.
export function parseAmount(v) {
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  let s = String(v ?? '').replace(/₺|tl|try/gi, '').replace(/\s/g, '');
  if (s.includes(',') && s.includes('.')) {
    s = s.lastIndexOf(',') > s.lastIndexOf('.') ? s.replace(/\./g, '').replace(',', '.') : s.replace(/,/g, '');
  } else if (s.includes(',')) {
    s = /^-?\d{1,3}(,\d{3}){2,}$/.test(s) ? s.replace(/,/g, '') : s.replace(',', '.');
  } else if (/^-?\d{1,3}(\.\d{3})+$/.test(s)) {
    s = s.replace(/\./g, '');
  }
  return /^-?\d+(\.\d+)?$/.test(s) ? Math.round(parseFloat(s) * 100) / 100 : null;
}
export const sameAmount = (a, b) =>
  parseAmount(a) !== null && parseAmount(b) !== null && Math.abs(parseAmount(a) - parseAmount(b)) < 0.005;

// Dotted path read: get(customer, 'card.last4').
export const get = (obj, key) => key.split('.').reduce((o, k) => (o == null ? undefined : o[k]), obj);

// Letters and digits only, folded: 'C-1001' == 'c1001', '0555 000 00 01' == '05550000001'.
export const loose = (s) => fold(s).replace(/[^\p{L}\p{N}]/gu, '');

// First item whose field (dotted path, or any of several) matches value loosely; phone fields
// compare the last 10 digits. findBy(customers, 'customer_id', ' C-1001 '), findBy(c.products, 'product_id', 'P1').
export function findBy(list, key, value) {
  if (value == null || loose(value) === '') return null;
  const keys = Array.isArray(key) ? key : [key];
  return (list ?? []).find((c) => keys.some((k) => {
    const v = get(c, k);
    if (v == null) return false;
    return /phone|tel|gsm|msisdn/i.test(k) ? samePhone(v, value) : loose(v) === loose(value);
  })) ?? null;
}
export const findCustomer = findBy;

// Enum value as the contract spells it: 'No Promise' / 'no-promise' -> 'no_promise' when allowed
// has it; anything else comes back folded and underscored (pass it through, or refuse it).
export function enumValue(v, allowed = []) {
  const k = fold(v).replace(/[\s-]+/g, '_');
  return allowed.find((a) => fold(a) === k) ?? k;
}

// null when every field is present, else a JSON error listing the missing ones.
export function requireFields(input, fields, status = 400) {
  const missing = fields.filter((f) => {
    const v = get(input ?? {}, f);
    return v == null || String(v).trim() === '';
  });
  return missing.length ? error(status, 'missing_fields', { missing, message: `missing: ${missing.join(', ')}` }) : null;
}
