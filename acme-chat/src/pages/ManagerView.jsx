/**
 * Manager view: status, currency, accountability -- and the only view that can
 * action an erasure request.
 *
 * Every panel except "Commitments and drift" is built from the free index
 * endpoints, so this page loads instantly and spends nothing.
 */
import { useMemo, useState } from 'react';
import { erasePerson } from '../lib/api.js';
import { useArchive } from '../lib/ArchiveContext.jsx';
import { useReports } from '../lib/ReportsContext.jsx';
import ViewShell, { Panel } from '../components/ViewShell.jsx';

const VIEW = 'manager';

const CANNED = [
  {
    id: 'never-done',
    label: 'What was agreed and then never done?',
    question:
      'Find one thing in the archive that was agreed and then never done. Show the trail from the agreement to the present, and say who would have needed to notice.',
    note: 'Full sweep — needs whole-timeline coverage',
    sweep: true,
  },
  {
    id: 'reports-true',
    label: 'Are the weekly status reports telling the truth?',
    question:
      'The weekly status reports say the nightly article extract completed with no errors. Is that true? Answer the question the reports are actually evidence for, and say what they are not evidence for.',
    note: 'Full sweep — cross-checks reports against incidents',
    sweep: true,
  },
  {
    id: 'uat',
    label: 'Was UAT actually signed off, and for what scope?',
    question:
      'Did Acme sign off UAT for the programme? Quote the scope of what was actually signed, and name who signed it.',
    note: 'Fast path — targeted lookup',
    sweep: false,
  },
];

function cleanName(p) {
  return p.replace(/\s*\(.*\)\s*$/, '').trim();
}

export default function ManagerView() {
  const { stats, documents, byDateDesc, internal, people } = useArchive();

  const gaps = useMemo(() => {
    const dated = [...byDateDesc].reverse();
    const out = [];
    for (let i = 1; i < dated.length; i += 1) {
      const days = Math.round(
        (new Date(dated[i].date) - new Date(dated[i - 1].date)) / 86400000,
      );
      if (days > 0) out.push({ days, from: dated[i - 1], to: dated[i] });
    }
    return out.sort((a, b) => b.days - a.days).slice(0, 3);
  }, [byDateDesc]);

  const participation = useMemo(() => {
    const counts = new Map();
    documents.forEach((d) => (d.participants || []).forEach((p) => {
      const n = cleanName(p);
      if (n) counts.set(n, (counts.get(n) || 0) + 1);
    }));
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8);
  }, [documents]);

  const byPhase = useMemo(() => {
    // Only transcripts carry a phase; email threads and reports do not, so
    // lumping them into "Unphased" would bury the real programme shape.
    const m = new Map();
    documents.filter((d) => d.phase).forEach((d) => {
      if (!m.has(d.phase)) m.set(d.phase, []);
      m.get(d.phase).push(d);
    });
    return [...m.entries()]
      .map(([phase, docs]) => {
        const dates = docs.map((d) => d.date).filter(Boolean).sort();
        return { phase, count: docs.length, from: dates[0], to: dates[dates.length - 1] };
      })
      .sort((a, b) => (a.from || '').localeCompare(b.from || ''));
  }, [documents]);

  return (
    <ViewShell
      view={VIEW}
      accent="#10a37f"
      title="Manager"
      subtitle="Status, currency and accountability across the programme"
    >
      {/* JSX children are built before ViewShell's loading guard runs, so the
          panels that read `stats` are gated here rather than inside the shell. */}
      {stats && <div className="view-grid">
        <Panel title="At a glance" note="no model calls">
          <div className="stat-grid">
            <Stat value={stats.documents} label="documents" />
            <Stat value={stats.units.toLocaleString()} label="citable units" />
            <Stat value={stats.truncated_units} label="cut off mid-sentence" />
            <Stat value={internal.length} label="internal-only" />
          </div>
          <div className="cost-hint">
            Covers {stats.date_range[0]?.slice(0, 10)} to {stats.date_range[1]?.slice(0, 10)}.
            Nothing after that date exists in the archive.
          </div>
        </Panel>

        <Panel title="Programme phases" note="transcripts only">
          <div className="row-list">
            {byPhase.map((p) => (
              <div key={p.phase} className="row-item">
                <div className="row-top">
                  <span className="row-title">{p.phase}</span>
                  <span className="row-date">{p.count} docs</span>
                </div>
                <div className="row-sub">{p.from?.slice(0, 10)} → {p.to?.slice(0, 10)}</div>
              </div>
            ))}
          </div>
          <div className="cost-hint">
            Email threads and status reports carry no phase, so they are not counted here.
          </div>
        </Panel>

        <Panel title="Latest activity" note="most recent first">
          <div className="row-list">
            {byDateDesc.slice(0, 6).map((d) => (
              <div key={d.doc_id} className="row-item">
                <div className="row-top">
                  <span className="row-title">{d.title}</span>
                  <span className="row-date">{d.date?.slice(0, 10)}</span>
                </div>
                <div className="row-sub">
                  {d.kind}
                  {d.internal && <> · <span className="tag warn">internal only</span></>}
                  {d.participants?.length > 0 && ` · ${d.participants.length} participants`}
                </div>
              </div>
            ))}
          </div>
        </Panel>

        <Panel title="Longest silences" note="gaps with no document at all">
          <div className="row-list">
            {gaps.map((g, i) => (
              <div key={i} className="row-item">
                <div className="row-top">
                  <span className="row-title">{g.days} days with nothing recorded</span>
                </div>
                <div className="row-sub">
                  {g.from.date?.slice(0, 10)} → {g.to.date?.slice(0, 10)}
                </div>
              </div>
            ))}
          </div>
          <div className="cost-hint">
            A gap is not proof that nothing happened — only that nothing was archived.
          </div>
        </Panel>

        <Panel title="Who was in the room" note={`${people.length} people known`}>
          <div className="row-list">
            {participation.map(([name, n]) => (
              <div key={name} className="row-item">
                <div className="row-top">
                  <span className="row-title">{name}</span>
                  <span className="row-date">{n} meetings</span>
                </div>
              </div>
            ))}
          </div>
          {internal.length > 0 && (
            <div className="cost-hint">
              {internal.length} recordings were RELEX-internal. Nothing said in them is
              something the customer agreed to.
            </div>
          )}
        </Panel>

        <ErasurePanel />

        <CannedPanel />
      </div>}
    </ViewShell>
  );
}

/** Shortcuts into the same ask loop the chatbox uses, so they produce the
 *  same report card rather than a second, different-looking output. */
function CannedPanel() {
  const { runAsk, busy } = useReports();
  return (
    <Panel title="Commitments and drift" note="these spend tokens" wide>
      <div className="canned-row">
        {CANNED.map((c) => (
          <button key={c.id} className="btn btn-primary" disabled={busy}
                  onClick={() => runAsk(c.question, { sweep: c.sweep, label: c.label })}>
            {c.label}
          </button>
        ))}
      </div>
      <div className="cost-hint">
        {CANNED.map((c) => <div key={c.id}>{c.label} — {c.note}</div>)}
      </div>
    </Panel>
  );
}

function Stat({ value, label }) {
  return (
    <div className="stat">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

/** Erasure is a manager action. It is permanent and there is no ledger to undo it. */
function ErasurePanel() {
  const [name, setName] = useState('');
  const [confirming, setConfirming] = useState(false);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    setConfirming(false);
    try {
      setResult(await erasePerson(name.trim(), VIEW));
    } catch (err) {
      setResult({ error: err.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel title="Data-subject erasure" note="manager only · permanent">
      <input
        className="field"
        placeholder="Full name, e.g. Kwame Boateng"
        value={name}
        onChange={(e) => { setName(e.target.value); setConfirming(false); }}
        disabled={busy}
      />
      <div className="erase-actions">
        {!confirming ? (
          <button className="btn btn-danger" disabled={!name.trim() || busy}
                  onClick={() => setConfirming(true)}>
            Erase from index
          </button>
        ) : (
          <>
            <button className="btn btn-danger" disabled={busy} onClick={run}>
              {busy ? 'Erasing…' : `Yes, erase ${name.trim()}`}
            </button>
            <button className="btn" onClick={() => setConfirming(false)}>Cancel</button>
          </>
        )}
      </div>
      <div className="cost-hint">
        Redacts the live index and the corpus is left untouched. Nothing identifying the
        subject is recorded anywhere, so this <strong>cannot be undone from the app</strong> —
        rebuilding the index from the corpus is the only way back.
      </div>

      {result?.error && <div className="view-state error">{result.error}</div>}
      {result?.receipt && <ErasureReceipt receipt={result.receipt} check={result.verification} />}
    </Panel>
  );
}

function ErasureReceipt({ receipt, check }) {
  return (
    <div className="receipt">
      <div className="stat-grid">
        <Stat value={receipt.units_authored_removed} label="units withheld" />
        <Stat value={receipt.mention_replacements} label="mentions redacted" />
        <Stat value={receipt.documents_affected.length} label="documents touched" />
      </div>
      <div className="receipt-row">
        <span className={`tag ${check?.clean ? 'good' : 'bad'}`}>
          {check?.clean ? 'independent re-scan: no trace remains' : 're-scan found surviving traces'}
        </span>
      </div>
      {receipt.survived.length > 0 && (
        <div className="receipt-block">
          <h4>Facts that survived</h4>
          <p>Someone else stated them independently, so the fact stands while the attribution is gone.</p>
          <ul>{receipt.survived.map((s, i) => <li key={i}><code>{s.figure}</code></li>)}</ul>
        </div>
      )}
      {receipt.did_not_survive.length > 0 && (
        <div className="receipt-block">
          <h4>Facts that did not survive</h4>
          <p>They were the only source, so the archive no longer supports these.</p>
          <ul>{receipt.did_not_survive.map((s, i) => <li key={i}><code>{s.figure}</code></li>)}</ul>
        </div>
      )}
    </div>
  );
}
