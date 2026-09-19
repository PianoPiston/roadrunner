/**
 * An answer, rendered as a report rather than a chat reply.
 *
 * A bordered card in the view's accent colour: the question it answers at the
 * top, the verified findings inside, and the cost and citation tally along the
 * bottom. It reads as a document you could hand to someone, which a chat
 * bubble does not.
 */
import AnswerView from './AnswerView.jsx';
import { fmt } from '../lib/usage.js';
import './ReportCard.css';

export default function ReportCard({ report, onDismiss }) {
  const { question, label, sweep, bundle, error } = report;
  const usage = bundle?.usage;
  const spent = usage ? (usage.triage_input_tokens + usage.triage_output_tokens
    + usage.synth_input_tokens + usage.synth_output_tokens) : 0;

  return (
    <article className={`report ${error ? 'report-error' : ''}`}>
      <header className="report-head">
        <div className="report-q">
          <span className="report-kicker">{label || 'Report'}</span>
          <h2>{question}</h2>
        </div>
        <button className="report-dismiss" onClick={() => onDismiss(report.id)} title="Dismiss">×</button>
      </header>

      <div className="report-body">
        {error
          ? <div className="report-fail">{error}</div>
          : <AnswerView bundle={bundle} showTrace />}
      </div>

      {!error && (
        <footer className="report-foot">
          <span className="tag">{sweep ? 'full sweep · all 45 documents' : 'fast path · tools only'}</span>
          <span className="tag">{fmt(spent)} tokens</span>
          {usage?.synth_model && <span className="tag">{usage.synth_model}</span>}
        </footer>
      )}
    </article>
  );
}

/** The placeholder shown while a question is in flight. */
export function PendingReport({ pending }) {
  return (
    <article className="report report-pending">
      <header className="report-head">
        <div className="report-q">
          <span className="report-kicker">{pending.label || 'Report'}</span>
          <h2>{pending.question}</h2>
        </div>
      </header>
      <div className="report-body">
        <div className="report-progress">
          <span className="dot" /><span className="dot" /><span className="dot" />
          <span className="report-progress-text">
            {pending.sweep
              ? 'Reading all 45 documents, then verifying every citation — this takes about a minute.'
              : 'Searching the index and verifying citations — a few seconds.'}
          </span>
        </div>
      </div>
    </article>
  );
}
