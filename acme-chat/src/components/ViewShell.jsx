/**
 * Common chrome for the three role views.
 *
 * Layout is the same everywhere: a header with the usage badge, a scrolling
 * body holding the view's own panels with any reports accumulating beneath
 * them, and the chatbox pinned to the bottom. The chatbox is identical in all three
 * three views -- same component, same behaviour, same coverage -- only the
 * accent colour changes.
 */
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useArchive } from '../lib/ArchiveContext.jsx';
import { ReportsProvider, useReports } from '../lib/ReportsContext.jsx';
import ChatInput from './ChatInput.jsx';
import ReportCard, { PendingReport } from './ReportCard.jsx';
import UsageBadge from './UsageBadge.jsx';
import './ViewShell.css';

export default function ViewShell({ view, title, subtitle, accent, children }) {
  return (
    <ReportsProvider view={view}>
      <Shell view={view} title={title} subtitle={subtitle} accent={accent}>
        {children}
      </Shell>
    </ReportsProvider>
  );
}

function Shell({ view, title, subtitle, accent, children }) {
  const { loading, error } = useArchive();
  const { reports, pending, runAsk, dismiss, busy } = useReports();
  const [input, setInput] = useState('');
  const reportsRef = useRef(null);

  // Reports sit below the panels, so scroll down to the newest one rather than
  // jumping to the top of the page.
  useEffect(() => {
    if (pending || reports.length) {
      reportsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, [pending, reports.length]);

  const send = () => {
    const q = input;
    setInput('');
    runAsk(q);
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

      <div className="view-body">
        {loading && <div className="view-state">Loading the archive index…</div>}
        {error && (
          <div className="view-state error">
            Could not reach the backend: {error}
            <div className="view-state-hint">Is <code>acme-agent serve --port 8000</code> running?</div>
          </div>
        )}

        {!loading && !error && (
          <>
            {/* The panels are what the view is for, so they stay at the top.
                Reports accumulate underneath them. */}
            {children}
            {(pending || reports.length > 0) && (
              <div className="reports" ref={reportsRef}>
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
          </>
        )}
      </div>

      <div className="view-chat">
        <div className="view-chat-opts">
          <span className="view-chat-cost">
            Every question reads all 45 documents before answering.
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
