/**
 * The shared ask loop behind every view's chatbox.
 *
 * One question in, one report out. The reports live here rather than in each
 * view so the chatbox behaves identically everywhere, and so a view's own
 * buttons (the manager's canned questions, for instance) produce exactly the
 * same report card as typing the question by hand.
 */
import { createContext, useCallback, useContext, useState } from 'react';
import { ask } from './api.js';

const ReportsContext = createContext(null);

let nextId = 1;

export function ReportsProvider({ view, defaultSweep, children }) {
  const [reports, setReports] = useState([]);
  const [pending, setPending] = useState(null);

  const runAsk = useCallback(async (question, { sweep = defaultSweep, label } = {}) => {
    const q = question.trim();
    if (!q) return;
    const id = nextId++;
    setPending({ id, question: q, label, sweep });
    try {
      const bundle = await ask(q, { view, runSweep: sweep });
      setReports((r) => [{ id, question: q, label, sweep, bundle }, ...r]);
    } catch (err) {
      setReports((r) => [{ id, question: q, label, sweep, error: err.message }, ...r]);
    } finally {
      setPending(null);
    }
  }, [view, defaultSweep]);

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
