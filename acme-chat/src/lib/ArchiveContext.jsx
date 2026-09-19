/**
 * The archive's free data, fetched once and shared by every view.
 *
 * Switching views costs nothing because nothing is re-fetched, and because
 * none of this involves a model call in the first place.
 */
import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { getDocuments, getPeople, getStats } from './api.js';

const ArchiveContext = createContext(null);

export function ArchiveProvider({ children }) {
  const [state, setState] = useState({ loading: true, error: null, stats: null, documents: [], people: [] });

  useEffect(() => {
    let alive = true;
    Promise.all([getStats(), getDocuments(), getPeople()])
      .then(([stats, documents, people]) => {
        if (alive) setState({ loading: false, error: null, stats, documents, people });
      })
      .catch((err) => alive && setState((s) => ({ ...s, loading: false, error: err.message })));
    return () => { alive = false; };
  }, []);

  const value = useMemo(() => {
    const { documents } = state;
    const dated = documents.filter((d) => d.date).sort((a, b) => b.date.localeCompare(a.date));
    return {
      ...state,
      /** Newest first. */
      byDateDesc: dated,
      transcripts: documents.filter((d) => d.kind === 'transcript'),
      emails: documents.filter((d) => d.kind === 'email'),
      reports: documents.filter((d) => d.kind === 'report'),
      internal: documents.filter((d) => d.internal),
      phases: [...new Set(documents.map((d) => d.phase).filter(Boolean))],
    };
  }, [state]);

  return <ArchiveContext.Provider value={value}>{children}</ArchiveContext.Provider>;
}

export function useArchive() {
  const ctx = useContext(ArchiveContext);
  if (!ctx) throw new Error('useArchive must be used inside <ArchiveProvider>');
  return ctx;
}
