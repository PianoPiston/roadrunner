/**
 * The shared ask loop behind every view's chatbox.
 *
 * One question in, one report out. The reports live here rather than in each
 * view so the chatbox behaves identically everywhere, and so a view's own
 * buttons (the manager's canned questions, for instance) produce exactly the
 * same report card as typing the question by hand.
 *
 * Every question runs the full sweep: the cheap model reads all 45 documents
 * before the analyst answers. There is deliberately no way to ask for less --
 * an answer that skipped part of the archive cannot be trusted to say what the
 * archive does NOT contain, and that is most of what this system is for.
 */
import { createContext, useCallback, useContext, useState } from 'react';
import { ask } from './api.js';

const ReportsContext = createContext(null);

let nextId = 1;

export function ReportsProvider({ view, children }) {
  const [reports, setReports] = useState([]);
  const [pending, setPending] = useState(null);

  const runAsk = useCallback(async (question, { label } = {}) => {
    const q = question.trim();
    if (!q) return;
    const id = nextId++;
    setPending({ id, question: q, label });
    try {
      const bundle = await ask(q, { view });
      setReports((r) => [{ id, question: q, label, bundle }, ...r]);
    } catch (err) {
      setReports((r) => [{ id, question: q, label, error: err.message }, ...r]);
    } finally {
      setPending(null);
    }
  }, [view]);

  const dismiss = useCallback((id) => {
    setReports((r) => r.filter((x) => x.id !== id));
  }, []);

  return (
    <ReportsContext.Provider value={{ reports, pending, runAsk, dismiss, busy: pending !== null }}>
      {children}
    </ReportsContext.Provider>
  );
}

export function useReports() {
  const ctx = useContext(ReportsContext);
  if (!ctx) throw new Error('useReports must be used inside <ReportsProvider>');
  return ctx;
}
