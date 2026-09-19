/**
 * Common chrome for the three role views: title bar, back link, usage badge,
 * and the loading/error states for the shared archive fetch.
 */
import { Link } from 'react-router-dom';
import { useArchive } from '../lib/ArchiveContext.jsx';
import UsageBadge from './UsageBadge.jsx';
import './ViewShell.css';

export default function ViewShell({ view, title, subtitle, accent, children }) {
  const { loading, error } = useArchive();

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
        {error && <div className="view-state error">Could not reach the backend: {error}
          <div className="view-state-hint">Is <code>acme-agent serve --port 8000</code> running?</div>
        </div>}
        {!loading && !error && children}
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
