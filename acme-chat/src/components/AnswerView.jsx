/**
 * Renders a structured answer bundle.
 *
 * The citation metadata shown here (document, speaker, date, locator) is the
 * backend's, read from the index -- not the model's. A quote the verifier
 * rejected is marked, never quietly printed as though it were sound.
 */
import './AnswerView.css';

const STATUS_TAG = {
  current: null,
  superseded: ['warn', 'superseded'],
  disputed: ['warn', 'disputed'],
  unverifiable: ['warn', 'unverifiable'],
  not_in_archive: ['bad', 'not in the archive'],
};

export default function AnswerView({ bundle, showTrace }) {
  if (!bundle) return null;
  const { answer, citations, verification, tool_calls: toolCalls, elapsed_s: elapsed } = bundle;
  const byId = Object.fromEntries(citations.map((c) => [c.unit_id + c.quote, c]));

  return (
    <div className="answer">
      <p className="answer-prose">{answer.answer}</p>

      {answer.claims.length > 0 && (
        <div className="answer-section">
          <h3>Claims and sources</h3>
          <ol className="answer-claims">
            {answer.claims.map((claim, i) => {
              const tag = STATUS_TAG[claim.status];
              return (
                <li key={i}>
                  <div className="claim-statement">
                    {claim.statement}
                    {tag && <span className={`tag ${tag[0]}`}>{tag[1]}</span>}
                  </div>
                  {claim.citations.map((cit, j) => {
                    const v = byId[cit.unit_id + cit.quote] || citations.find((c) => c.unit_id === cit.unit_id);
                    const ok = v?.ok;
                    return (
                      <div key={j} className={`citation ${ok ? '' : 'citation-bad'}`}>
                        <div className="citation-quote">“{cit.quote.trim()}”</div>
                        <div className="citation-ref">
                          {v?.reference || cit.unit_id}
                          {!ok && <span className="tag bad">unverified</span>}
                          {v?.match === 'approximate' && <span className="tag warn">not verbatim</span>}
                        </div>
                      </div>
                    );
                  })}
                  {claim.superseded_by && (
                    <div className="claim-superseded">superseded by <code>{claim.superseded_by}</code></div>
                  )}
                </li>
              );
            })}
          </ol>
        </div>
      )}

      {answer.gaps.length > 0 && (
        <div className="answer-section">
          <h3>What the archive does not say</h3>
          {answer.gaps.map((g, i) => (
            <div key={i} className="answer-gap">
              <strong>{g.question_part}</strong> — {g.what_is_missing} {g.why_it_cannot_be_answered}
              {g.nearest_evidence && <> Nearest: <code>{g.nearest_evidence}</code>.</>}
            </div>
          ))}
        </div>
      )}

      {answer.abstentions.length > 0 && (
        <div className="answer-section">
          <h3>Left incomplete on purpose</h3>
          {answer.abstentions.map((a, i) => (
            <div key={i} className="answer-gap">
              <code>{a.unit_id}</code>: “{a.what_was_being_said}” — {a.why_not_completed}
            </div>
          ))}
        </div>
      )}

      <div className="answer-foot">
        <span className={`tag ${verification.clean ? 'good' : 'bad'}`}>
          {verification.citations_verified}/{verification.citations_total} citations verified
        </span>
        <span className="tag">confidence {answer.confidence}</span>
        {elapsed && <span className="tag">{elapsed.toFixed(1)}s</span>}
        {verification.citations_failed.length > 0 && (
          <span className="answer-failed">failed: {verification.citations_failed.join(', ')}</span>
        )}
      </div>

      {verification.warnings?.length > 0 && (
        <ul className="answer-warnings">
          {verification.warnings.map((w, i) => <li key={i}>{w}</li>)}
        </ul>
      )}

      {answer.method_note && <p className="answer-method">{answer.method_note}</p>}

      {showTrace && toolCalls?.length > 0 && (
        <div className="answer-section">
          <h3>Tool calls</h3>
          <div className="answer-trace mono">
            {toolCalls.map((c, i) => (
              <div key={i}>
                {i + 1}. {c.tool}
                <span className="trace-args">
                  {Object.entries(c).filter(([k]) => k !== 'tool')
                    .map(([k, val]) => ` ${k}=${JSON.stringify(val)}`).join('')}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
