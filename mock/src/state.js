// What the agent did that would change something at the bank (week changes, PDF sends), kept
// ONLY for observation (/__state). The answers never read it: this mock is a pure table lookup
// over test-customers.json, so every request gets the same answer whatever happened before
// (several simulations may share a customer at the same time).
//
// Deployed, it lives in the one Durable Object (worker.js), which saves snapshot() after each
// change and restore()s it when it starts. In node tests it is plain memory.

export const MAX_RECORDS = 300; // oldest dropped first, so the saved state stays small

let records = []; // [{ id, kind, customerNo, at, ...fields }]
let seq = 0;

export function record(kind, customerNo, fields = {}) {
  const entry = { id: `${kind.slice(0, 3).toUpperCase()}-${String(++seq).padStart(4, '0')}`, kind,
    customerNo: customerNo == null ? null : String(customerNo), at: new Date().toISOString(), ...fields };
  records.push(entry);
  if (records.length > MAX_RECORDS) records = records.slice(-MAX_RECORDS);
  return entry;
}

// /__state: records grouped by customer, then by kind (oldest first).
export function dump() {
  const byCustomer = {};
  for (const r of records) ((byCustomer[r.customerNo ?? '?'] ??= {})[r.kind] ??= []).push(r);
  return { note: 'observation only: answers never depend on this', count: records.length, records: byCustomer };
}

export const snapshot = () => ({ seq, records });

export function restore(snap) {
  reset();
  if (!snap) return;
  seq = snap.seq ?? 0;
  records = Array.isArray(snap.records) ? snap.records : [];
}

export function reset() {
  records = [];
  seq = 0;
}
