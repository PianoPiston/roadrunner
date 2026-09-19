"""Deterministic search and rendering. No model calls happen in this file.

Search is not a replacement for the cheap-model sweep; it is the cheap thing
that makes the sweep cheaper, and the exact thing a language model is bad at:
finding *every* occurrence of "OP_ID", or every percentage in the archive with
its date attached.

Rendering matters just as much. Every rendered unit carries its id, date,
speaker and locator inline, so the model can cite without being asked to
remember a mapping, and so a hallucinated id is immediately detectable.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from .core import Store, Unit

# ══════════════════════════════════════════════════════════════════════════
# Search
# ══════════════════════════════════════════════════════════════════════════

_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9_\-.%]*")
_STOP = {
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "for",
    "is", "are", "was", "were", "be", "been", "it", "that", "this", "with",
    "as", "at", "by", "from", "we", "i", "you", "they", "he", "she", "not",
    "so", "do", "does", "did", "have", "has", "had", "will", "would", "can",
    "could", "should", "there", "their", "them", "what", "which", "who",
}


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)
            if t.lower() not in _STOP and len(t) > 1]


@dataclass
class Hit:
    unit: Unit
    score: float
    why: str = ""


class BM25:
    """Classic BM25 over unit text. Built once per request, cheap enough."""

    def __init__(self, units: list[Unit], k1: float = 1.5, b: float = 0.75) -> None:
        self.units, self.k1, self.b = units, k1, b
        docs = [tokenize(u.text) for u in units]
        self.freqs = [Counter(d) for d in docs]
        self.lens = [len(d) for d in docs]
        self.avgdl = (sum(self.lens) / len(self.lens)) if self.lens else 0.0
        df: Counter[str] = Counter()
        for f in self.freqs:
            df.update(f.keys())
        n = len(units)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def search(self, query: str, top_k: int = 40) -> list[Hit]:
        q = tokenize(query)
        if not q:
            return []
        scored: list[Hit] = []
        for i, freq in enumerate(self.freqs):
            s = 0.0
            for t in q:
                f = freq.get(t, 0)
                if f:
                    denom = f + self.k1 * (1 - self.b + self.b * self.lens[i] / (self.avgdl or 1))
                    s += self.idf.get(t, 0.0) * (f * (self.k1 + 1)) / denom
            if s > 0:
                scored.append(Hit(unit=self.units[i], score=round(s, 4)))
        scored.sort(key=lambda h: -h.score)
        return scored[:top_k]


def grep(store: Store, pattern: str, regex: bool = False, ignore_case: bool = True,
         limit: int = 100) -> list[Hit]:
    """Exhaustive exact or regex match, with surrounding context."""
    rx = re.compile(pattern if regex else re.escape(pattern), re.I if ignore_case else 0)
    out: list[Hit] = []
    for u in store.units:
        if u.redacted:
            continue
        m = rx.search(u.text)
        if m:
            start = max(0, m.start() - 90)
            out.append(Hit(unit=u, score=1.0,
                           why="…" + u.text[start:m.end() + 90].replace("\n", " ") + "…"))
            if len(out) >= limit:
                break
    return out


# Percentages, counts, money, spelled-out numbers. A "currency" question is
# usually "give me every figure with its date", which is a scan, not a search.
FIGURE_RE = re.compile(
    r"(?P<fig>"
    r"\d{1,3}(?:[.,]\d+)?\s?%"
    r"|(?:EUR|€|\$|£)\s?\d[\d.,]*\s?(?:k|m|bn|million|thousand)?"
    r"|\d[\d.,]*\s?(?:k|m|bn)\b"
    r"|\b\d{1,3}(?:[.,]\d{3})+\b"
    r"|\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand)"
    r"(?:[ -](?:one|two|three|four|five|six|seven|eight|nine|ten|hundred|thousand|"
    r"percent|per cent))*\s*(?:percent|per cent)\b"
    r"|\b\d{1,4}\s*(?:articles|items|stores|SKUs|skus|days|weeks|months|users|"
    r"incidents|defects|rows|files|people)\b"
    r")", re.I,
)


def find_figures(store: Store, topic: str | None = None, limit: int = 200) -> list[dict]:
    """Every numeric claim, with its date and source, oldest first."""
    topic_tokens = set(tokenize(topic)) if topic else set()
    out: list[dict] = []
    for u in store.chronological():
        if u.redacted:
            continue
        if topic_tokens and not (topic_tokens & set(tokenize(u.text))):
            continue
        for m in FIGURE_RE.finditer(u.text):
            s = max(0, m.start() - 110)
            out.append({
                "figure": m.group("fig").strip(),
                "context": re.sub(r"\s+", " ", u.text[s:m.end() + 110]).strip(),
                "unit_id": u.unit_id,
                "doc_id": u.doc_id,
                "date": u.date,
                "speaker": u.speaker_display,
                "locator": u.locator,
                "truncated_statement": u.truncated,
            })
            if len(out) >= limit:
                return out
    return out


# ══════════════════════════════════════════════════════════════════════════
# Rendering
# ══════════════════════════════════════════════════════════════════════════

def render_unit(u: Unit) -> str:
    """One unit with its provenance and integrity flags inline."""
    bits = [b for b in (u.date,
                        f"{u.speaker_display}{f'/{u.speaker_org}' if u.speaker_org else ''}"
                        if u.speaker_display else None,
                        u.locator) if b]
    head = f"[{u.unit_id}]" + (f" ({' | '.join(bits)})" if bits else "")

    flags = []
    if u.truncated:
        flags.append("!! CUT OFF mid-sentence and never resumed -- do NOT complete it")
    if u.meta.get("attachments_stripped"):
        flags.append(f"!! {u.meta['attachments_stripped']} attachment(s) referenced but NOT in the archive")
    if u.meta.get("unattributed_dialect"):
        flags.append("!! speaker labels are only 'Me'/'Them' -- individual identity unknown")
    if u.interrupted_by:
        flags.append("interrupted by: " + " / ".join(u.interrupted_by[:3]))
    tail = ("\n    " + "\n    ".join(flags)) if flags else ""
    return f"{head}\n{u.text}{tail}"


def render_document(store: Store, doc_id: str, include_redacted: bool = False) -> str:
    doc = store.doc(doc_id)
    if not doc:
        return ""
    units = [u for u in store.doc_units(doc_id) if include_redacted or not u.redacted]

    header = [f"DOCUMENT: {doc.doc_id}", f"kind: {doc.kind}", f"title: {doc.title}"]
    if doc.date:
        header.append(f"latest date in document: {doc.date}")
    if doc.meta.get("first_date"):
        header.append(f"earliest date in document: {doc.meta['first_date']}")
    if doc.phase:
        header.append(f"phase: {doc.phase}")
    if doc.internal:
        header.append("NOTE: internal RELEX-only recording; the customer was not present")
    if doc.participants:
        header.append("participants: " + ", ".join(doc.participants))
    if doc.kind in ("email", "report"):
        header.append("NOTE: thread is stored newest-first. Each message below carries its OWN "
                      "date. Do not attribute the newest date to older messages.")
    n_red = sum(1 for u in store.doc_units(doc_id) if u.redacted)
    if n_red and not include_redacted:
        header.append(f"NOTE: {n_red} unit(s) withheld under an erasure request.")

    return "\n".join(header) + "\n\n" + "\n\n".join(render_unit(u) for u in units)


def render_evidence(units: list[Unit], store: Store) -> str:
    """Chronological evidence block for the synthesis stage."""
    out = []
    for u in store.chronological(units):
        doc = store.doc(u.doc_id)
        ctx = f"  <source: {doc.title if doc else u.doc_id}"
        if doc and doc.internal:
            ctx += "; INTERNAL RELEX-only recording"
        out.append(render_unit(u) + ctx + ">")
    return "\n\n".join(out)


def corpus_overview(store: Store) -> str:
    """What the archive does and does not contain, as a table."""
    lines = ["ARCHIVE INVENTORY", ""]
    for d in sorted(store.documents, key=lambda d: (d.kind, d.doc_id)):
        n = len([u for u in store.doc_units(d.doc_id) if not u.redacted])
        span = d.meta.get("first_date") or d.date
        rng = span[:10] if span else "?"
        if d.date and span and d.date[:10] != rng:
            rng = f"{rng}..{d.date[:10]}"
        flag = " [INTERNAL]" if d.internal else ""
        lines.append(f"  {d.meta.get('short','?'):5s} {d.doc_id:60s} {d.kind:10s} "
                     f"{rng:24s} {n:4d} units{flag}")
    s = store.stats()
    lines += ["", f"totals: {s['documents']} documents, {s['units']} units, "
                  f"range {s['date_range'][0]} to {s['date_range'][1]}"]
    return "\n".join(lines)
