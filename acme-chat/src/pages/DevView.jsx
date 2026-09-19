/**
 * Developer view: exact lookups against the index.
 *
 * Grep, the unit inspector and the quote checker are all deterministic and
 * free -- they are the things a language model is bad at. The chatbox below
 * them defaults to the fast path (no 45-document sweep) because most developer
 * questions are lookups, not questions about absence.
 */
import { useState } from 'react';
import { getUnit, grep, verifyQuote } from '../lib/api.js';
import { useArchive } from '../lib/ArchiveContext.jsx';
import ViewShell, { Panel } from '../components/ViewShell.jsx';

const VIEW = 'dev';

export default function DevView() {
  const { stats } = useArchive();

  return (
    <ViewShell
      view={VIEW}
      accent="#7aa2f7"
      title="Developer"
      subtitle="Exact, deterministic lookups — no model unless you ask for one"
      defaultSweep={false}
    >
      {stats && (
        <div className="view-grid">
          <GrepPanel />
          <UnitPanel />
          <VerifyPanel />
          <HealthPanel stats={stats} />
        </div>
      )}
    </ViewShell>
  );
}

function GrepPanel() {
  const [pattern, setPattern] = useState('OP_ID');
  const [regex, setRegex] = useState(false);
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    if (!pattern.trim()) return;
    setBusy(true);
    try {
      setRes(await grep(pattern, regex, VIEW));
    } catch (err) {
      setRes({ error: err.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel title="Exact search" note="literal or regex · 0 tokens" wide>
      <div className="dev-row">
        <input
          className="field"
          value={pattern}
          onChange={(e) => setPattern(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && run()}
          placeholder="OP_ID, DC-2, shelf life…"
        />
        <label className="dev-check">
          <input type="checkbox" checked={regex} onChange={(e) => setRegex(e.target.checked)} />
          regex
        </label>
        <button className="btn btn-primary" onClick={run} disabled={busy}>
          {busy ? '…' : 'Search'}
        </button>
      </div>

      {res?.error && <div className="view-state error">{res.error}</div>}
      {res && !res.error && (
        <>
          <div className="cost-hint">
            {res.count === 0
              ? `Nothing contains "${res.pattern}". That is evidence of absence: the archive does not use the term.`
              : `${res.count} unit${res.count === 1 ? '' : 's'} matched.`}
          </div>
          <div className="row-list dev-results">
            {res.hits.map((h) => (
              <div key={h.unit_id} className="row-item">
                <div className="row-top">
                  <span className="row-title mono">{h.unit_id}</span>
                  <span className="row-date">{h.date?.slice(0, 10) || '—'}</span>
                </div>
                <div className="row-sub">
                  {h.speaker || 'unattributed'} · {h.locator}
                  {h.truncated && <> · <span className="tag warn">cut off</span></>}
                </div>
                <div className="dev-context">{h.context}</div>
              </div>
            ))}
          </div>
        </>
      )}
    </Panel>
  );
}

function UnitPanel() {
  const [id, setId] = useState('T06.s0008');
  const [unit, setUnit] = useState(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try {
      setUnit(await getUnit(id.trim(), VIEW));
    } catch (err) {
      setUnit({ error: err.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel title="Unit inspector" note="raw record · 0 tokens">
      <div className="dev-row">
        <input className="field mono" value={id} onChange={(e) => setId(e.target.value)}
               onKeyDown={(e) => e.key === 'Enter' && run()} placeholder="T06.s0008" />
        <button className="btn btn-primary" onClick={run} disabled={busy}>Fetch</button>
      </div>

      {unit?.error && <div className="view-state error">{unit.error}</div>}
      {unit?.missing && (
        <div className="cost-hint">
          <span className="tag bad">404</span> No such unit. It never existed.
        </div>
      )}
      {unit?.withheld && (
        <div className="cost-hint">
          <span className="tag warn">410 Gone</span> Withheld under an erasure request —
          which is a different fact from &ldquo;never existed&rdquo;. {unit.reason}
        </div>
      )}
      {unit?.unit_id && (
        <div className="dev-unit">
          <div className="row-sub">
            {unit.date || 'undated'} · {unit.speaker_display || 'unattributed'}
            {unit.speaker_org && ` (${unit.speaker_org})`} · {unit.locator}
          </div>
          <div className="dev-unit-text">{unit.text}</div>
          <div className="dev-tags">
            {unit.truncated && <span className="tag warn">truncated</span>}
            {unit.redacted && <span className="tag bad">redacted</span>}
            {unit.interrupted_by?.length > 0 && (
              <span className="tag">{unit.interrupted_by.length} interruptions</span>
            )}
            {unit.spans_units?.length > 1 && (
              <span className="tag">stitched from {unit.spans_units.length}</span>
            )}
          </div>
          {unit.interrupted_by?.length > 0 && (
            <div className="dev-interrupts">
              {unit.interrupted_by.map((iv, i) => <div key={i}>{iv}</div>)}
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}

function VerifyPanel() {
  const [id, setId] = useState('T06.s0008');
  const [quote, setQuote] = useState('shelf life is populated on forty-eight percent');
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try {
      setRes(await verifyQuote(id.trim(), quote, VIEW));
    } catch (err) {
      setRes({ problem: err.message, ok: false });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel title="Citation checker" note="is this quote real? · 0 tokens">
      <input className="field mono" value={id} onChange={(e) => setId(e.target.value)}
             placeholder="unit id" />
      <textarea className="field dev-textarea" rows={3} value={quote}
                onChange={(e) => setQuote(e.target.value)} placeholder="the exact words…" />
      <button className="btn btn-primary" onClick={run} disabled={busy}>
        {busy ? '…' : 'Check'}
      </button>

      {res && (
        <div className="dev-verify">
          <span className={`tag ${res.ok ? (res.match === 'exact' ? 'good' : 'warn') : 'bad'}`}>
            {res.ok ? (res.match === 'exact' ? 'verbatim' : 'close, not verbatim') : 'fabricated'}
          </span>
          {res.problem && <div className="row-sub">{res.problem}</div>}
          {res.reference && <div className="row-sub mono">{res.reference}</div>}
        </div>
      )}
    </Panel>
  );
}

function HealthPanel({ stats }) {
  return (
    <Panel title="Index health" note="no model calls">
      <div className="stat-grid">
        <div className="stat">
          <div className="stat-value">{stats.units.toLocaleString()}</div>
          <div className="stat-label">units</div>
        </div>
        <div className="stat">
          <div className="stat-value">{stats.truncated_units}</div>
          <div className="stat-label">truncated</div>
        </div>
        <div className="stat">
          <div className="stat-value">{stats.redacted_units}</div>
          <div className="stat-label">redacted</div>
        </div>
        <div className="stat">
          <div className="stat-value">{stats.people}</div>
          <div className="stat-label">people</div>
        </div>
      </div>
      <div className="dev-kv mono">
        <div><span>fingerprint</span>{stats.corpus_fingerprint}</div>
        <div><span>built</span>{stats.built_at}</div>
        <div><span>by kind</span>{Object.entries(stats.units_by_kind).map(([k, v]) => `${k} ${v}`).join(' · ')}</div>
      </div>
    </Panel>
  );
}
