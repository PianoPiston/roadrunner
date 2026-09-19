/**
 * Common chrome for the three role views.
 *
 * Layout is the same everywhere: a header with the usage badge, a scrolling
 * body holding any reports produced so far followed by the view's own panels,
 * and the chatbox pinned to the bottom. The chatbox is identical in all three
 * views -- same component, same behaviour -- only the default sweep setting
 * and the accent colour change.
 */
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useArchive } from '../lib/ArchiveContext.jsx';
import { ReportsProvider, useReports } from '../lib/ReportsContext.jsx';
import ChatInput from './ChatInput.jsx';
import ReportCard, { PendingReport } from './ReportCard.jsx';
import UsageBadge from './UsageBadge.jsx';
import './ViewShell.css';

export default function ViewShell({ view, title, subtitle, accent, defaultSweep = true, children }) {
  return (
    <ReportsProvider view={view} defaultSweep={defaultSweep}>
      <Shell view={view} title={title} subtitle={subtitle} accent={accent} defaultSweep={defaultSweep}>
        {children}
      </Shell>
    </ReportsProvider>
  );
}

function Shell({ view, title, subtitle, accent, defaultSweep, children }) {
  const { loading, error } = useArchive();
  const { reports, pending, runAsk, dismiss, busy } = useReports();
  const [input, setInput] = useState('');
  const [sweep, setSweep] = useState(defaultSweep);
  const bodyRef = useRef(null);

  // A new report lands at the top of the stack, so bring it into view.
  useEffect(() => {
    if (pending || reports.length) bodyRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
  }, [pending, reports.length]);

  const send = () => {
    const q = input;
    setInput('');
    runAsk(q, { sweep });
  };

  return (
    <div className="view" style={accent ? { '--view-accent': accent } : undefined}>
      <header className="view-header">
        <Link to="/" className="view-back" title="Choose a different view">←</Link>
        <div className="view-titles">
          <h1>{title}</h1>
          {subtitle && <p>{subtitle}</p>}
        </div>
        <UsageBadge view={view} />
      </header>

      <div className="view-body" ref={bodyRef}>
        {loading && <div className="view-state">Loading the archive index…</div>}
        {error && (
          <div className="view-state error">
            Could not reach the backend: {error}
            <div className="view-state-hint">Is <code>acme-agent serve --port 8000</code> running?</div>
          </div>
        )}

        {!loading && !error && (
          <>
            {(pending || reports.length > 0) && (
              <div className="reports">
                <div className="reports-head">
                  <h3>{reports.length + (pending ? 1 : 0)} report{reports.length + (pending ? 1 : 0) === 1 ? '' : 's'}</h3>
                  {reports.length > 1 && (
                    <button className="reports-clear" onClick={() => reports.forEach((r) => dismiss(r.id))}>
                      clear all
                    </button>
                  )}
                </div>
                {pending && <PendingReport pending={pending} />}
                {reports.map((r) => <ReportCard key={r.id} report={r} onDismiss={dismiss} />)}
              </div>
            )}
            {children}
          </>
        )}
      </div>

      <div className="view-chat">
        <div className="view-chat-opts">
          <label className="dev-check">
            <input type="checkbox" checked={sweep} disabled={busy}
                   onChange={(e) => setSweep(e.target.checked)} />
            full sweep — read all 45 documents
          </label>
          <span className="view-chat-cost">
            {sweep ? 'thorough, ~1 min, needed for questions about absence'
                   : 'fast path, a few seconds, ~45× cheaper'}
          </span>
        </div>
        <ChatInput
          value={input}
          onChange={setInput}
          onSend={send}
          disabled={busy}
          placeholder={busy ? 'Running acme-agent…' : 'Ask the archive…'}
        />
      </div>
    </div>
  );
}

/** A titled box. Every panel in every view uses this, so they stay consistent. */
export function Panel({ title, note, children, wide }) {
  return (
    <section className={`panel ${wide ? 'panel-wide' : ''}`}>
      <div className="panel-head">
        <h2>{title}</h2>
        {note && <span className="panel-note">{note}</span>}
      </div>
      <div className="panel-body">{children}</div>
    </section>
  );
}
