/**
 * Landing page: pick a role. Each card explains what that view is for and what
 * it can do that the others cannot -- including, explicitly, that erasure is
 * the manager's alone.
 */
import { Link } from 'react-router-dom';
import { useArchive } from '../lib/ArchiveContext.jsx';
import './Home.css';

const VIEWS = [
  {
    to: '/dev',
    accent: '#7aa2f7',
    name: 'Developer',
    tagline: 'Exact lookups against the index',
    blurb:
      'Literal and regex search over every unit, a raw inspector for any unit id, and a standalone citation checker that tells you whether a quote is real — all deterministic, all instant, none of it involving a model.',
    can: ['Grep and regex', 'Raw unit JSON', 'Verify a quote', 'Tool-call trace'],
    cannot: 'Cannot erase people.',
  },
  {
    to: '/manager',
    accent: '#10a37f',
    name: 'Manager',
    tagline: 'Status, currency and accountability',
    blurb:
      'The programme end to end: what happened when, who was in the room, where the archive goes quiet, and what was agreed and then never done. This is also the only view that can action a data-subject erasure request.',
    can: ['Phase timeline', 'Latest activity', 'Coverage gaps', 'Commitment tracking'],
    cannot: 'Can erase people — permanently.',
    danger: true,
  },
  {
    to: '/marketing',
    accent: '#c58af9',
    name: 'Marketing',
    tagline: 'The story, and what is safe to tell',
    blurb:
      'The narrative arc from first demo to renewal, headline numbers, and quotable lines. Every quote is checked against the index before it is shown, and anything superseded, cut off, or said in an internal-only meeting is held back.',
    can: ['Story timeline', 'Dated figures', 'Verified quotes', 'Publish clearance'],
    cannot: 'Cannot erase people.',
  },
];

export default function Home() {
  const { stats, loading, error } = useArchive();

  return (
    <div className="home">
      <div className="home-inner">
        <header className="home-head">
          <h1>Acme archive</h1>
          <p>
            One citation-grounded agent over {stats ? stats.documents : '45'} documents.
            Choose the view that matches what you need to do.
          </p>
          {stats && (
            <div className="home-stats">
              <span>{stats.units.toLocaleString()} citable units</span>
              <span>{stats.people} people</span>
              <span>{stats.date_range[0]?.slice(0, 7)} → {stats.date_range[1]?.slice(0, 7)}</span>
              {stats.redacted_units > 0 && (
                <span className="home-stat-warn">{stats.redacted_units} withheld</span>
              )}
            </div>
          )}
          {error && <div className="home-error">Backend unreachable: {error}. Start it with <code>acme-agent serve --port 8000</code>.</div>}
          {loading && <div className="home-loading">Loading index…</div>}
        </header>

        <div className="home-cards">
          {VIEWS.map((v) => (
            <Link key={v.to} to={v.to} className="home-card" style={{ '--card-accent': v.accent }}>
              <div className="home-card-head">
                <span className="home-card-dot" />
                <h2>{v.name}</h2>
              </div>
              <p className="home-card-tagline">{v.tagline}</p>
              <p className="home-card-blurb">{v.blurb}</p>
              <ul className="home-card-can">
                {v.can.map((c) => <li key={c}>{c}</li>)}
              </ul>
              <div className={`home-card-cannot ${v.danger ? 'danger' : ''}`}>{v.cannot}</div>
            </Link>
          ))}
        </div>

        <footer className="home-foot">
          Every view shows a token counter. Loading a view, searching, and checking a
          quote all cost <strong>zero</strong> tokens — only asking the agent a question
          spends any, and that is always behind a button you press.
        </footer>
      </div>
    </div>
  );
}
