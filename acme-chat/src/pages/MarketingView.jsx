/**
 * Marketing view: the story, and what is safe to tell.
 *
 * The risk this view is built around is specific: reusing a superseded figure
 * in a case study. The archive is full of them -- shelf-life coverage is stated
 * as 48% three times and is wrong; 61% is current and carries a scope
 * qualifier. So every figure here is dated, the latest value for a given
 * wording is marked, and anything cut off mid-sentence or said in an
 * internal-only meeting is held back rather than shown as quotable.
 *
 * All of it is free: dates, figures and speakers come from the index.
 */
import { useMemo, useState } from 'react';
import { getFigures, grep, verifyQuote } from '../lib/api.js';
import { useArchive } from '../lib/ArchiveContext.jsx';
import ViewShell, { Panel } from '../components/ViewShell.jsx';

const VIEW = 'marketing';

export default function MarketingView() {
  const { stats, byDateDesc, internal, people } = useArchive();

  const customerNames = useMemo(
    () => new Set(people.filter((p) => p.org === 'Acme').map((p) => p.display)),
    [people],
  );

  const story = useMemo(() => {
    const asc = [...byDateDesc].reverse();
    const pick = (re) => asc.find((d) => re.test(d.doc_id));
    return [
      ['First contact', pick(/solution-demo|value-workshop/)],
      ['Commercials', pick(/sow-review|commercial/)],
      ['Kickoff', pick(/implementation-kickoff/)],
      ['Go live', pick(/go-live|cutover/)],
      ['Steady state', pick(/hypercare|continuous-service/)],
      ['Most recent', asc[asc.length - 1]],
    ].filter(([, d]) => d);
  }, [byDateDesc]);

  return (
    <ViewShell
      view={VIEW}
      accent="#c58af9"
      title="Marketing"
      subtitle="The story so far — and what the archive will actually support in public"
    >
      {stats && (
        <div className="view-grid">
          <Panel title="The arc" note="from document dates" wide>
            <div className="story">
              {story.map(([label, d]) => (
                <div key={label} className="story-beat">
                  <div className="story-date">{d.date?.slice(0, 10)}</div>
                  <div className="story-label">{label}</div>
                  <div className="story-title">{d.title}</div>
                </div>
              ))}
            </div>
            <div className="cost-hint">
              {stats.date_range[0]?.slice(0, 10)} to {stats.date_range[1]?.slice(0, 10)} —
              roughly {Math.round(
                (new Date(stats.date_range[1]) - new Date(stats.date_range[0])) / 2629800000,
              )} months from first demo to the latest record.
            </div>
          </Panel>

          <FiguresPanel />
          <VoicePanel customerNames={customerNames} />

          <Panel title="Before you publish" note="standing rules" wide>
            <div className="clearance">
              <div className="clearance-col hold">
                <h4>Hold</h4>
                <ul>
                  <li><strong>{stats.truncated_units} cut-off statements.</strong> Someone began a
                    sentence and never finished it. There is no figure there to quote.</li>
                  <li><strong>{internal.length} internal-only recordings.</strong> The customer was
                    not present, so nothing in them is a customer endorsement.</li>
                  <li><strong>Any older value of a number.</strong> Check the date column before
                    using a figure — the newest wording is the one that stands.</li>
                  {stats.redacted_units > 0 && (
                    <li><strong>{stats.redacted_units} withheld units.</strong> Erased at a data
                      subject&rsquo;s request; do not reconstruct them.</li>
                  )}
                </ul>
              </div>
              <div className="clearance-col ok">
                <h4>Safe to use</h4>
                <ul>
                  <li>Quotes that come back <strong>verbatim</strong> from the checker below.</li>
                  <li>Figures shown as the <strong>latest</strong> mention, with their date attached.</li>
                  <li>Anything a named Acme person said in a meeting they attended.</li>
                </ul>
              </div>
            </div>
          </Panel>
        </div>
      )}
    </ViewShell>
  );
}

function FiguresPanel() {
  const [topic, setTopic] = useState('shelf life');
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try {
      setRes(await getFigures(topic, VIEW));
    } catch (err) {
      setRes({ error: err.message });
    } finally {
      setBusy(false);
    }
  };

  // Mark the newest mention of each distinct value. This is a dating fact, not
  // a semantic judgement -- the agent decides what truly supersedes what.
  const marked = useMemo(() => {
    if (!res?.figures) return [];
    const newest = new Map();
    res.figures.forEach((f) => {
      const k = f.figure.toLowerCase();
      if (!newest.has(k) || (f.date || '') > (newest.get(k) || '')) newest.set(k, f.date || '');
    });
    return res.figures.map((f) => ({
      ...f,
      isLatest: (f.date || '') === newest.get(f.figure.toLowerCase()),
    })).reverse();
  }, [res]);

  return (
    <Panel title="Figures, dated" note="0 tokens">
      <div className="dev-row">
        <input className="field" value={topic} onChange={(e) => setTopic(e.target.value)}
               onKeyDown={(e) => e.key === 'Enter' && run()} placeholder="shelf life, waste, uptime…" />
        <button className="btn btn-primary" onClick={run} disabled={busy}>
          {busy ? '…' : 'Find'}
        </button>
      </div>

      {res?.error && <div className="view-state error">{res.error}</div>}
      {res && !res.error && res.count === 0 && (
        <div className="empty">No figures on “{res.topic}”.</div>
      )}
      {marked.length > 0 && (
        <>
          <div className="cost-hint">Newest first. Use the top one, and quote its date with it.</div>
          <div className="row-list dev-results">
            {marked.map((f, i) => (
              <div key={i} className="row-item">
                <div className="row-top">
                  <span className="row-title">{f.figure}</span>
                  <span className="row-date">{f.date?.slice(0, 10) || '—'}</span>
                </div>
                <div className="row-sub">
                  {f.speaker || 'unattributed'}
                  {' '}
                  {f.isLatest
                    ? <span className="tag good">latest wording</span>
                    : <span className="tag warn">earlier mention</span>}
                  {f.truncated_statement && <> <span className="tag bad">source cut off</span></>}
                </div>
                <div className="dev-context">…{f.context}…</div>
              </div>
            ))}
          </div>
        </>
      )}
    </Panel>
  );
}

/** Customer quotes only -- the vendor praising itself is not a testimonial. */
function VoicePanel({ customerNames }) {
  const [term, setTerm] = useState('waste');
  const [hits, setHits] = useState(null);
  const [checks, setChecks] = useState({});
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    setChecks({});
    try {
      const res = await grep(term, false, VIEW);
      setHits(res.hits.filter((h) => customerNames.has(h.speaker)));
    } catch (err) {
      setHits({ error: err.message });
    } finally {
      setBusy(false);
    }
  };

  const check = async (h) => {
    const quote = h.context.replace(/^…|…$/g, '').trim();
    const v = await verifyQuote(h.unit_id, quote, VIEW);
    setChecks((c) => ({ ...c, [h.unit_id]: v }));
  };

  return (
    <Panel title="Customer voice" note="Acme speakers only · 0 tokens">
      <div className="dev-row">
        <input className="field" value={term} onChange={(e) => setTerm(e.target.value)}
               onKeyDown={(e) => e.key === 'Enter' && run()} placeholder="waste, forecast, rollout…" />
        <button className="btn btn-primary" onClick={run} disabled={busy}>
          {busy ? '…' : 'Find'}
        </button>
      </div>
      <div className="cost-hint">
        Vendor voices are filtered out — only people at the customer count as a testimonial.
      </div>

      {hits?.error && <div className="view-state error">{hits.error}</div>}
      {Array.isArray(hits) && hits.length === 0 && (
        <div className="empty">No customer said that in the archive.</div>
      )}
      {Array.isArray(hits) && hits.length > 0 && (
        <div className="row-list dev-results">
          {hits.map((h) => (
            <div key={h.unit_id} className="row-item">
              <div className="row-top">
                <span className="row-title">{h.speaker}</span>
                <span className="row-date">{h.date?.slice(0, 10)}</span>
              </div>
              <div className="dev-context">…{h.context}…</div>
              <div className="voice-actions">
                {h.truncated
                  ? <span className="tag bad">cut off — do not quote</span>
                  : checks[h.unit_id]
                    ? <span className={`tag ${checks[h.unit_id].ok ? 'good' : 'bad'}`}>
                        {checks[h.unit_id].ok ? 'verified verbatim' : 'could not verify'}
                      </span>
                    : <button className="btn" onClick={() => check(h)}>Verify before quoting</button>}
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}
