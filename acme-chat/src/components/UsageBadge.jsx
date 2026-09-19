/**
 * Standardised token counter. Identical in all three views.
 *
 * Shows what this view has actually spent, from the backend's own accounting.
 * "free" counts requests that made no model call at all -- the whole point of
 * the manager and marketing views is that this number stays large and the
 * token counts stay at zero until someone deliberately asks a question.
 */
import { useEffect, useState } from 'react';
import { estimateCost, fmt, readUsage, resetUsage } from '../lib/usage.js';
import './UsageBadge.css';

export default function UsageBadge({ view }) {
  const [totals, setTotals] = useState(() => readUsage(view));
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const refresh = () => setTotals(readUsage(view));
    refresh();
    window.addEventListener('acme-usage', refresh);
    return () => window.removeEventListener('acme-usage', refresh);
  }, [view]);

  const cost = estimateCost(totals);
  const spent = totals.inputTokens + totals.outputTokens;

  return (
    <div className={`usage-badge ${open ? 'open' : ''}`}>
      <button className="usage-summary" onClick={() => setOpen((v) => !v)} title="Token usage for this view">
        <span className={`usage-dot ${spent === 0 ? 'zero' : ''}`} />
        <span className="usage-figure">{fmt(spent)}</span>
        <span className="usage-label">tokens</span>
        <span className="usage-sep">·</span>
        <span className="usage-label">{totals.requests} ask{totals.requests === 1 ? '' : 's'}</span>
      </button>

      {open && (
        <div className="usage-detail">
          <Row label="Model requests" value={totals.requests} />
          <Row label="Free requests (no model)" value={totals.freeRequests} />
          <Row label="Input tokens" value={fmt(totals.inputTokens)} />
          <Row label="of which cached" value={fmt(totals.cachedTokens)} dim />
          <Row label="Output tokens" value={fmt(totals.outputTokens)} />
          {cost !== null && <Row label="Estimated cost" value={`${cost.toFixed(4)}`} />}

          {Object.entries(totals.byModel).length > 0 && (
            <div className="usage-models">
              {Object.entries(totals.byModel).map(([model, m]) => (
                <div key={model} className="usage-model">
                  <span className="usage-model-name">{model}</span>
                  <span className="usage-model-nums">
                    {m.calls}× · in {fmt(m.input)}{m.cached ? ` (${fmt(m.cached)} cached)` : ''} · out {fmt(m.output)}
                  </span>
                </div>
              ))}
            </div>
          )}

          <button className="usage-reset" onClick={() => resetUsage(view)}>Reset counter</button>
        </div>
      )}
    </div>
  );
}

function Row({ label, value, dim }) {
  return (
    <div className={`usage-row ${dim ? 'dim' : ''}`}>
      <span>{label}</span>
      <span className="usage-row-value">{value}</span>
    </div>
  );
}
