/**
 * Backend calls, split by what they cost.
 *
 * Everything in FREE hits the in-memory index and makes no model calls, so a
 * view can load all of it eagerly. `ask` is the only expensive call and is
 * never fired automatically -- always behind an explicit click.
 */
import { recordAsk, recordFree } from './usage.js';

async function get(path, view) {
  const res = await fetch(`/api${path}`);
  if (!res.ok) throw new Error(`${path} -> HTTP ${res.status}`);
  if (view) recordFree(view);
  return res.json();
}

// --- free: no model calls -------------------------------------------------
export const getStats = (view) => get('/stats', view);
export const getDocuments = (view) => get('/documents', view);
export const getPeople = (view) => get('/people', view);
export const getDocument = (id, view) => get(`/documents/${id}`, view);
export const getFigures = (topic, view) =>
  get(`/figures?topic=${encodeURIComponent(topic || '')}`, view);
export const grep = (pattern, regex, view) =>
  get(`/grep?pattern=${encodeURIComponent(pattern)}&regex=${regex ? 'true' : 'false'}`, view);

/** A unit, distinguishing "withheld" (410) from "never existed" (404). */
export async function getUnit(unitId, view) {
  const res = await fetch(`/api/units/${encodeURIComponent(unitId)}`);
  if (view) recordFree(view);
  if (res.status === 410) return { withheld: true, ...(await res.json()).detail };
  if (res.status === 404) return { missing: true };
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function verifyQuote(unitId, quote, view) {
  const res = await fetch('/api/verify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ unit_id: unitId, quote }),
  });
  if (view) recordFree(view);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// --- expensive: model calls ----------------------------------------------

/**
 * Ask the agent. `runSweep: false` skips the 45-document triage pass, which is
 * roughly 45x cheaper and a few seconds instead of a minute -- right for
 * lookups, wrong for questions about absence.
 */
export async function ask(question, { view, runSweep = true } = {}) {
  const res = await fetch('/api/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, run_sweep: runSweep }),
  });
  if (!res.ok) throw new Error((await res.text()).slice(0, 300) || `HTTP ${res.status}`);
  const bundle = await res.json();
  if (view) recordAsk(view, bundle.usage);
  return bundle;
}

/** Erasure. Manager view only -- permanent, with no ledger to replay it back. */
export async function erasePerson(name, view) {
  const res = await fetch('/api/erase', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  if (view) recordFree(view);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}
