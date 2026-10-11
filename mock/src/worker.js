// The bank-services mock (Freya Bank voice services). Routes and the lookup come from routes.js,
// the test customers from data.js (generated from test-customers.json).
//
// Deployed with the MOCK binding (wrangler.toml), the Worker forwards every request to one
// Durable Object, MockState "main", which runs the router below single-threaded: state and
// request log are the same whichever isolate or colo got the request. The DO saves them to its
// storage after each request that changed them and loads them when it starts, so they survive
// its eviction. Without the binding (node tests, or a deploy without it) the router runs in
// the Worker's own memory.
import * as contract from './routes.js';
import { error, json, setErrorBody } from './util.js';
import { dump, reset, restore, snapshot } from './state.js';

const { BASE, routes, customers } = contract;
const settings = contract.settings ?? {};
// routes.js may export errorBody(status, code, extra): every error, the worker's own included,
// then has the contract's shape. Without it: { ok: false, error: code, ...extra }.
setErrorBody(contract.errorBody);

const CORS = {
  'access-control-allow-origin': '*',
  'access-control-allow-methods': 'GET, POST, PUT, PATCH, DELETE, OPTIONS',
  'access-control-max-age': '86400',
};
const LOG_SIZE = 120;
const LOG_SAVE_BYTES = 160 * 1024; // the saved copy of the log drops its oldest entries past this
const log = []; // with the state: in the DO, or in this isolate without one
let logVersion = 0;

const routeList = () => routes.map((r) => `${r.method.toUpperCase()} ${r.root ? '' : BASE}${r.path}`);

// Path without trailing slash and without BASE (so tool URLs with or without it both work).
function localPath(pathname) {
  const p = pathname.replace(/\/+$/, '') || '/';
  return BASE && (p === BASE || p.startsWith(BASE + '/')) ? p.slice(BASE.length) || '/' : p;
}

function decode(s) {
  try { return decodeURIComponent(s); } catch { return s; }
}

// Params for a '/a/{id}/b' template, or null when the path does not fit it.
function matchPath(template, path) {
  const t = (template.replace(/\/+$/, '') || '/').split('/');
  const p = path.split('/');
  if (t.length !== p.length) return null;
  const params = {};
  for (let i = 0; i < t.length; i++) {
    const m = /^\{(\w+)\}$/.exec(t[i]);
    if (m && p[i]) params[m[1]] = decode(p[i]);
    else if (t[i] !== p[i]) return null;
  }
  return params;
}

function parseBody(raw, contentType, path) {
  if (!raw.trim()) return {};
  if ((contentType || '').includes('form-urlencoded')) return Object.fromEntries(new URLSearchParams(raw));
  try {
    return JSON.parse(raw);
  } catch (e) {
    // The token endpoint takes a form body whatever the content type says.
    if (path === '/oauth2/token') return Object.fromEntries(new URLSearchParams(raw));
    // A variable written without quotes ("customerNo": {{customerNumber}}) left unfilled: quote it,
    // so it is refused like any unknown value (the service's 404/400, template_warning in the log).
    if (/\{\{/.test(raw)) {
      try { return JSON.parse(raw.replace(/(?<!")\{\{\s*[\w.\-]+\s*\}\}(?!")/g, (m) => JSON.stringify(m))); } catch { /* still bad */ }
    }
    throw e;
  }
}

// settings.REQUIRED_HEADERS ({ 'x-kanal': 'sesli-asistan' }; true or '*' = any non-empty value):
// each request to a route logs the values it got (secret-looking names only as '<set>') and a
// header_warning when one is missing or different. Refused (settings.HEADER_ERROR, default
// 400 invalid_header) only when settings.REQUIRE_HEADERS is true.
function checkHeaders(request, note) {
  const want = Object.entries(settings.REQUIRED_HEADERS ?? {});
  if (!want.length) return null;
  const got = {}, wrong = [];
  for (const [name, value] of want) {
    const v = request.headers.get(name);
    const secret = /auth|key|token|secret|pass/i.test(name);
    got[name.toLowerCase()] = v == null ? null : secret ? '<set>' : v;
    const any = value === true || value === '*';
    if (v == null || v.trim() === '') wrong.push(`${name} missing`);
    else if (!any && v.trim() !== String(value)) wrong.push(secret ? `${name} wrong` : `${name} '${v}', want '${value}'`);
  }
  note({ headers: got, ...(wrong.length && { header_warning: wrong.join('; ') }) });
  if (!wrong.length || !settings.REQUIRE_HEADERS) return null;
  const he = settings.HEADER_ERROR ?? {};
  return error(he.status ?? 400, he.error ?? 'invalid_header', { message: he.message ?? wrong.join('; ') });
}

// notes: fields a handler adds to this request's log entry with ctx.note({ order_warning: ... }).
async function dispatch(request, env, url, query, body, notes) {
  const path = localPath(url.pathname);
  const allowed = [];
  for (const r of routes) {
    const params = matchPath(r.path, path);
    if (!params) continue;
    if (r.method.toUpperCase() !== request.method) {
      allowed.push(r.method.toUpperCase());
      continue;
    }
    const input = { ...query, ...(body && typeof body === 'object' && !Array.isArray(body) ? body : {}) };
    const note = (fields) => Object.assign(notes, fields);
    const refused = checkHeaders(request, note);
    if (refused) return refused;
    const out = await r.handler({ request, env, params, query, body, input, customers, note });
    return out instanceof Response ? out : json(out === undefined ? { ok: true } : out);
  }
  if (allowed.length) {
    return error(405, 'method_not_allowed', { allowed, message: `${request.method} not allowed here; use ${allowed.join(', ')}` },
      { allow: allowed.join(', ') });
  }
  return error(404, 'not_found', { message: `no route for ${request.method} ${url.pathname}; routes: ${routeList().join(', ')}` });
}

// Inspection endpoints, not logged: health, request log, recorded state, reset.
function admin(method, path, url, store) {
  const key = `${method} ${path}`;
  if (key === 'GET /__health') return json({ ok: true, routes: routes.length, customers: customers.length, store });
  if (key === 'GET /') return json({ ok: true, base: BASE, routes: routeList() });
  if (key === 'GET /__log') {
    const n = Number(url.searchParams.get('limit')) || LOG_SIZE;
    return json({ count: log.length, entries: log.slice(-n) });
  }
  if (key === 'GET /__state') return json(dump());
  if (key === 'POST /__reset') {
    log.length = 0;
    logVersion++;
    reset();
    return json({ ok: true });
  }
  return null;
}

function withCors(res) {
  const headers = new Headers(res.headers);
  for (const [k, v] of Object.entries(CORS)) headers.set(k, v);
  return new Response(res.body, { status: res.status, headers });
}

async function remember(entry, res) {
  const text = await res.clone().text();
  try { entry.response = JSON.parse(text); } catch { entry.response = text; }
  log.push(entry);
  if (log.length > LOG_SIZE) log.shift();
  logVersion++;
  console.log(JSON.stringify(entry)); // one line per request in `wrangler tail`
}

// The router: CORS, inspection endpoints, routes, request log. store: where state lives.
async function handle(request, env = {}, store = 'memory') {
  try {
    const url = new URL(request.url);
    if (request.method === 'OPTIONS') {
      const asked = request.headers.get('access-control-request-headers');
      return new Response(null, {
        status: 204,
        headers: { ...CORS, 'access-control-allow-headers': asked || 'content-type, authorization' },
      });
    }
    const adminRes = admin(request.method, localPath(url.pathname), url, store);
    if (adminRes) return withCors(adminRes);

    const query = Object.fromEntries(url.searchParams);
    const raw = ['GET', 'HEAD'].includes(request.method) ? '' : await request.text();
    const notes = {};
    let body, res;
    try {
      body = parseBody(raw, request.headers.get('content-type'), localPath(url.pathname));
    } catch (e) {
      body = raw;
      res = error(400, 'bad_json', { message: `request body is not valid JSON: ${e.message}` });
    }
    if (!res) {
      res = await dispatch(request, env, url, query, body, notes)
        .catch((e) => error(500, 'internal_error', { message: String(e?.message ?? e) }));
    }
    res = withCors(res);
    const entry = { time: new Date().toISOString(), method: request.method, path: url.pathname, query, body, status: res.status, ...notes };
    await remember(entry, res);
    return res;
  } catch (e) {
    return withCors(error(500, 'internal_error', { message: String(e?.message ?? e) }));
  }
}

// The one Durable Object that holds the state (binding MOCK, name "main").
export class MockState {
  constructor(ctx, env) {
    this.ctx = ctx;
    this.env = env;
    this.ready = ctx.blockConcurrencyWhile(async () => {
      const saved = await ctx.storage.get(['state', 'log']); // a Map
      restore(saved.get('state'));
      log.splice(0, log.length, ...(saved.get('log') ?? []));
      this.savedState = JSON.stringify(snapshot());
      this.savedLog = logVersion;
    });
  }

  async fetch(request) {
    await this.ready;
    const res = await handle(request, this.env, 'durable_object');
    await this.save();
    return res;
  }

  // Writes state and log when this request changed them. A failed write is logged, and the
  // agent still gets its answer.
  async save() {
    const state = JSON.stringify(snapshot());
    if (state === this.savedState && logVersion === this.savedLog) return;
    let saveLog = log.slice();
    while (saveLog.length && JSON.stringify(saveLog).length > LOG_SAVE_BYTES) saveLog = saveLog.slice(Math.ceil(saveLog.length / 4));
    try {
      await this.ctx.storage.put({ state: JSON.parse(state), log: saveLog });
      this.savedState = state;
      this.savedLog = logVersion;
    } catch (e) {
      console.error(JSON.stringify({ error: 'state_not_saved', message: String(e?.message ?? e) }));
    }
  }
}

export default {
  async fetch(request, env = {}) {
    if (!env.MOCK) return handle(request, env);
    try {
      return await env.MOCK.get(env.MOCK.idFromName('main')).fetch(request);
    } catch (e) {
      return withCors(error(500, 'state_unavailable', { message: String(e?.message ?? e) }));
    }
  },
};
