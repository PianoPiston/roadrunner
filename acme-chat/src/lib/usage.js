/**
 * Per-view token counter.
 *
 * Numbers come from the backend's own accounting (`bundle.usage`), never from
 * an estimate here. Free endpoints record a zero-token request, so the counter
 * visibly proves that loading the manager or marketing view costs nothing.
 *
 * Totals persist in localStorage so they survive a reload mid-demo.
 */

const KEY = (view) => `acme.usage.${view}`;

// Set to null to hide money entirely. Units: currency per 1M tokens.
// Fill these in from your provider's current price list if you want costs shown.
export const RATES = null; // e.g. { 'gpt-5': { in: 0, out: 0 }, 'gpt-5-mini': { in: 0, out: 0 } }

const EMPTY = {
  requests: 0,
  freeRequests: 0,
  inputTokens: 0,
  cachedTokens: 0,
  outputTokens: 0,
  byModel: {},
};

export function readUsage(view) {
  try {
    const raw = localStorage.getItem(KEY(view));
    return raw ? { ...EMPTY, ...JSON.parse(raw) } : { ...EMPTY };
  } catch {
    return { ...EMPTY }; // private mode, blocked storage: counter still renders
  }
}

function write(view, totals) {
  try {
    localStorage.setItem(KEY(view), JSON.stringify(totals));
  } catch {
    /* non-fatal: the in-memory value still drives the badge this session */
  }
  window.dispatchEvent(new CustomEvent('acme-usage', { detail: { view } }));
}

/** Record a request that made no model calls. */
export function recordFree(view) {
  const t = readUsage(view);
  t.freeRequests += 1;
  write(view, t);
}

/** Record a real /ask response, using the backend's own usage block. */
export function recordAsk(view, usage) {
  if (!usage) return;
  const t = readUsage(view);
  t.requests += 1;

  const add = (model, input, cached, output) => {
    if (!model) return;
    t.inputTokens += input || 0;
    t.cachedTokens += cached || 0;
    t.outputTokens += output || 0;
    const m = t.byModel[model] || { input: 0, cached: 0, output: 0, calls: 0 };
    m.input += input || 0;
    m.cached += cached || 0;
    m.output += output || 0;
    m.calls += 1;
    t.byModel[model] = m;
  };

  add(usage.triage_model, usage.triage_input_tokens, usage.triage_cached_tokens,
      usage.triage_output_tokens);
  add(usage.synth_model, usage.synth_input_tokens, 0, usage.synth_output_tokens);

  write(view, t);
}

export function resetUsage(view) {
  write(view, { ...EMPTY, byModel: {} });
}

export function estimateCost(totals) {
  if (!RATES) return null;
  let cost = 0;
  for (const [model, m] of Object.entries(totals.byModel)) {
    const r = RATES[model];
    if (!r) continue;
    cost += ((m.input - m.cached) / 1e6) * r.in + (m.output / 1e6) * r.out;
  }
  return cost;
}

export function fmt(n) {
  if (n < 1000) return String(n);
  if (n < 1e6) return `${(n / 1000).toFixed(n < 10000 ? 1 : 0)}k`;
  return `${(n / 1e6).toFixed(2)}M`;
}
