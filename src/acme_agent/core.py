"""Configuration, record types, the person registry, and the loaded index.

Two ideas here carry the whole system:

* A **Unit** is the atom of the archive: one dated, attributed, quotable span.
  Every claim the agent makes must point at one, by an id that is stable across
  rebuilds -- derived from document and ordinal position, never from content
  hashing -- so a citation stays valid after a re-parse.

* A **Registry** maps every surface form of a person onto one identity:
  "Kwame Boateng", "Kwame", "Boateng", "k.boateng@relexsolutions.example" and
  the Teams-export initials "KB" are the same human. Attribution and erasure
  both stand or fall here.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal

from dotenv import load_dotenv

# ══════════════════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════════════════

load_dotenv()

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _path(env: str, default: str) -> Path:
    p = Path(os.getenv(env, default)).expanduser()
    return p if p.is_absolute() else (_REPO_ROOT / p).resolve()


@dataclass(frozen=True)
class Config:
    """Runtime settings, all overridable by environment variable."""

    corpus_dir: Path = _path("ACME_CORPUS_DIR", "corpus/acme")
    data_dir: Path = _path("ACME_DATA_DIR", "data")

    # The cheap model runs once per document (45 calls per question); the
    # expensive one runs once, over the evidence the cheap pass kept.
    triage_model: str = os.getenv("ACME_TRIAGE_MODEL", "gpt-5.4-mini")
    synth_model: str = os.getenv("ACME_SYNTH_MODEL", "gpt-5.6-terra")

    triage_concurrency: int = int(os.getenv("ACME_TRIAGE_CONCURRENCY", "12"))
    # Documents scoring at or above this are passed to the synthesis stage.
    triage_keep_threshold: int = int(os.getenv("ACME_TRIAGE_KEEP_THRESHOLD", "2"))
    # Hard ceiling on evidence units handed to the expensive model.
    max_evidence_units: int = int(os.getenv("ACME_MAX_EVIDENCE_UNITS", "160"))

    @property
    def index_path(self) -> Path:
        return self.data_dir / "index.json"


CONFIG = Config()


# ══════════════════════════════════════════════════════════════════════════
# Records
# ══════════════════════════════════════════════════════════════════════════

DocKind = Literal["transcript", "email", "report"]


@dataclass
class Person:
    pid: str
    display: str
    org: str | None = None
    role: str | None = None
    emails: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    # True when the person only ever appears as a mention, never as an author.
    mention_only: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Unit:
    """One citable span of the archive."""

    unit_id: str
    doc_id: str
    doc_kind: DocKind
    seq: int
    text: str

    # Provenance -------------------------------------------------------
    date: str | None = None            # ISO 8601, of THIS unit, not the thread
    speaker: str | None = None         # canonical person id
    speaker_display: str | None = None
    speaker_org: str | None = None
    recipients: list[str] = field(default_factory=list)

    # Citation anchor, human readable: "at 12:35" / "message 3 of 4"
    locator: str = ""

    # Currency / integrity flags ---------------------------------------
    truncated: bool = False            # statement is cut off and never resumes
    interrupted_by: list[str] = field(default_factory=list)
    spans_units: list[str] = field(default_factory=list)  # atomic ids stitched in

    # Redaction --------------------------------------------------------
    redacted: bool = False
    redaction_note: str | None = None

    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Unit":
        return cls(**d)


@dataclass
class Document:
    doc_id: str
    kind: DocKind
    path: str
    title: str
    date: str | None = None
    phase: str | None = None
    participants: list[str] = field(default_factory=list)
    subject: str | None = None
    n_units: int = 0
    internal: bool = False             # RELEX-only recording
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Document":
        return cls(**d)


# ══════════════════════════════════════════════════════════════════════════
# Person registry
# ══════════════════════════════════════════════════════════════════════════

# The seed roster is curated; everyone else is discovered from the corpus, so
# off-roster people (Nils Ackermann, Osman Yildirim, the Acme staff who appear
# only as an email address) are first-class too. `org` matters for attribution:
# "who agreed" reads differently if the speaker is the vendor.
_SEED: list[tuple[str, str, str, str]] = [
    # (display, org, role, email)
    ("Lena Fischer", "Acme", "Head of Supply Chain", "lena.fischer@acme-org.example"),
    ("Robert Kahn", "Acme", "CFO", "robert.kahn@acme-org.example"),
    ("Sofia Almeida", "Acme", "Category Manager, Fresh", "sofia.almeida@acme-org.example"),
    ("Priya Nair", "Acme", "IT Integration Lead", "priya.nair@acme-org.example"),
    ("Jonas Weiss", "Acme", "Category Manager, Ambient", "jonas.weiss@acme-org.example"),
    ("Katarina Voss", "Acme", "Data Protection Officer", "katarina.voss@acme-org.example"),
    ("Marco Rossi", "RELEX", "Account Executive", "marco.rossi@relexsolutions.example"),
    ("Ana Duarte", "RELEX", "Project Manager", "ana.duarte@relexsolutions.example"),
    ("Nadia Haddad", "RELEX", "Solution Consultant", "n.haddad@relexsolutions.example"),
    ("Tomas Lindholm", "RELEX", "Solution Architect", "tomas.lindholm@relexsolutions.example"),
    ("Kwame Boateng", "RELEX", "Technical Consultant", "k.boateng@relexsolutions.example"),
    ("Charlotte Meyer", "RELEX", "Service Delivery", "charlotte.meyer@relexsolutions.example"),
    ("Henrik Sørensen", "RELEX", "Account Director", "henrik.sorensen@relexsolutions.example"),
    ("Ivan Petrov", "Meridian Consulting", "Consultant", "i.petrov@meridian-consulting.example"),
    ("Ruth Oyelaran", "Meridian Consulting", "Consultant", "r.oyelaran@meridian-consulting.example"),
]

# Things that look like names to a regex but are not.
_NOT_PEOPLE = {
    "acme org", "meridian consulting", "relex solutions", "unknown speaker",
    "northwind retail", "retail group", "grocery retail", "supply chain",
    "image image", "weekly acme", "kind regards", "best regards",
}

# Sentence-initial words that pair up into fake "names" across a line break or
# at the start of a sentence: "The The", "Sollten Sie", "March This".
_STOPWORDS = {
    "the", "then", "she", "he", "they", "this", "that", "there", "these", "those",
    "it", "we", "you", "i", "and", "but", "so", "if", "when", "what", "which",
    "who", "how", "why", "where", "our", "their", "his", "her", "your", "my",
    "sollten", "sie", "wir", "das", "der", "die", "und", "mit", "von", "ist",
    "stockholm", "lisboa", "koln", "koeln", "connect", "bild", "image", "from",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "monday", "tuesday",
    "wednesday", "thursday", "friday", "saturday", "sunday", "best", "kind",
    "regards", "hi", "hello", "dear", "thanks", "thank", "subject", "re", "fw",
}

EMAIL_RE = re.compile(r"[\w.\-]+@[\w.\-]+\.[a-z]{2,}", re.I)


def fold(s: str) -> str:
    """Diacritic- and case-insensitive comparison key. Sørensen -> sorensen."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def slug(display: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", fold(display)).strip("_")


def initials(display: str) -> str:
    return "".join(p[0] for p in display.split() if p)[:3].upper()


def aliases_for(display: str, emails: list[str]) -> list[str]:
    """Every surface form a person is plausibly written as."""
    parts = [p for p in display.split() if p]
    out: set[str] = {display, fold(display)}
    if len(parts) >= 2:
        out.add(parts[0])              # Kwame
        out.add(parts[-1])             # Boateng
        out.add(f"{parts[0]} {parts[-1]}")
        out.add(initials(display))     # KB, as used in Teams exports
    # ASCII-folded spelling, e.g. Henrik Sorensen
    ascii_form = unicodedata.normalize("NFKD", display)
    ascii_form = "".join(c for c in ascii_form if not unicodedata.combining(c))
    out.add(ascii_form)
    if len(ascii_form.split()) >= 2:
        out.add(ascii_form.split()[-1])
    for e in emails:
        out.add(e)
        out.add(e.split("@")[0])       # k.boateng
        out.add(e.split("@")[0].replace(".", " "))
    return sorted(out)


@dataclass
class Registry:
    people: dict[str, Person]
    by_alias: dict[str, str]

    @classmethod
    def of(cls, people: dict[str, Person]) -> "Registry":
        by_alias: dict[str, str] = {}
        for pid, p in people.items():
            for a in [p.display, *p.aliases, *p.emails]:
                # First writer wins, so the seed roster beats discovered duplicates.
                by_alias.setdefault(fold(a), pid)
            by_alias.setdefault(fold(initials(p.display)), pid)
        return cls(people=people, by_alias=by_alias)

    def resolve(self, text: str | None) -> Person | None:
        """Map any surface form to a person. None if not a known person."""
        if not text:
            return None
        if fold(text) in self.by_alias:
            return self.people[self.by_alias[fold(text)]]
        # "Ana Duarte (RELEX)" and "Ana Duarte <a@b>" forms
        stripped = re.sub(r"\s*[(<\[].*$", "", text).strip()
        if stripped and fold(stripped) in self.by_alias:
            return self.people[self.by_alias[fold(stripped)]]
        m = EMAIL_RE.search(text)
        if m and fold(m.group(0).rstrip(".")) in self.by_alias:
            return self.people[self.by_alias[fold(m.group(0).rstrip("."))]]
        return None

    def search(self, needle: str) -> list[Person]:
        """Loose lookup, for when a caller types a name (the deletion API)."""
        p = self.resolve(needle)
        if p:
            return [p]
        k = fold(needle)
        return [p for p in self.people.values()
                if k in fold(p.display) or any(k == fold(a) for a in p.aliases)]

    def alias_patterns(self, pid: str) -> list[str]:
        """Every surface form of this person, longest first.

        Longest-first matters to the erasure engine: redact "Kwame Boateng"
        before the bare "Kwame" so the replacement is clean.
        """
        p = self.people[pid]
        return sorted({f for f in {p.display, *p.aliases, *p.emails} if f},
                      key=len, reverse=True)


def build_registry(corpus_text: str = "") -> Registry:
    """Seed roster plus anyone else the corpus mentions."""
    people: dict[str, Person] = {}
    for display, org, role, email in _SEED:
        pid = slug(display)
        people[pid] = Person(pid=pid, display=display, org=org, role=role,
                             emails=[email], aliases=aliases_for(display, [email]))
    if corpus_text:
        _discover(corpus_text, people)
    return Registry.of(people)


def _discover(text: str, people: dict[str, Person]) -> None:
    """Add people the seed roster misses."""
    known_emails = {fold(e) for p in people.values() for e in p.emails}

    # 1. Anyone with an email address in the archive.
    for raw in sorted(set(EMAIL_RE.findall(text))):
        e = raw.rstrip(".").lower()
        if fold(e) in known_emails:
            continue
        local = e.split("@")[0]
        if local in {"datenschutz", "info", "support", "noreply"}:
            continue  # role address, not a person
        display = " ".join(w.capitalize() for w in re.split(r"[._]", local) if w)
        pid = slug(display)
        if pid in people:
            people[pid].emails.append(e)
            continue
        domain = e.split("@")[1]
        org = ("Acme" if "acme" in domain else
               "RELEX" if "relex" in domain else
               "Meridian Consulting" if "meridian" in domain else None)
        people[pid] = Person(pid=pid, display=display, org=org, emails=[e],
                             aliases=aliases_for(display, [e]), mention_only=True)
        known_emails.add(fold(e))

    # 2. "Firstname Lastname" mentioned repeatedly in prose. The separator is
    # deliberately newline-free: "Lisboa\nConnect" is a signature block, not a
    # person.
    counts: dict[str, int] = {}
    for m in re.finditer(
        r"\b([A-ZÅÄÖØÆ][a-zåäöøæ]{2,})[^\S\n]+([A-ZÅÄÖØÆ][a-zåäöøæ\-]{2,})\b", text
    ):
        counts[m.group(0)] = counts.get(m.group(0), 0) + 1

    for name, n in counts.items():
        if n < 2 or fold(name) in _NOT_PEOPLE:
            continue
        if any(fold(t) in _STOPWORDS for t in name.split()):
            continue
        if slug(name) in people:
            continue
        # Skip if either token already belongs to a known person (partial match).
        toks = {fold(t) for t in name.split()}
        if any(toks & {fold(t) for t in p.display.split()} for p in people.values()):
            continue
        # Skip title-ish pairs, e.g. "Category Manager", "Delivery Lead".
        if re.search(r"\b(Manager|Consultant|Director|Officer|Lead|Architect|Executive|"
                     r"Attendees|Timeline|Image|Status|Retail|Chain|Phase|Group|Track|"
                     r"Delay|Risk|Configuration|Financial|Protection|Sales|Services)\b", name):
            continue
        people[slug(name)] = Person(pid=slug(name), display=name,
                                    aliases=aliases_for(name, []), mention_only=True)


# ══════════════════════════════════════════════════════════════════════════
# Store: the loaded index
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class Store:
    """The index in memory, with lookup and redaction awareness."""

    units: list[Unit]
    documents: list[Document]
    people: dict[str, Person]
    meta: dict
    path: Path = CONFIG.index_path

    registry: Registry = field(init=False)
    _by_id: dict[str, Unit] = field(init=False)
    _by_doc: dict[str, list[Unit]] = field(init=False)
    _docs: dict[str, Document] = field(init=False)

    def __post_init__(self) -> None:
        self.reindex()

    def reindex(self) -> None:
        """Rebuild the lookup tables. Called after any mutation."""
        self._by_id = {u.unit_id: u for u in self.units}
        self._by_doc = {}
        for u in self.units:
            self._by_doc.setdefault(u.doc_id, []).append(u)
        self._docs = {d.doc_id: d for d in self.documents}
        self.registry = Registry.of(self.people)

    # --- load / save -----------------------------------------------------
    @classmethod
    def load(cls, path: Path | None = None) -> "Store":
        path = path or CONFIG.index_path
        if not path.exists():
            raise FileNotFoundError(f"index not found at {path}. Run: acme-agent build")
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            units=[Unit.from_dict(u) for u in raw["units"]],
            documents=[Document.from_dict(d) for d in raw["documents"]],
            people={k: Person(**v) for k, v in raw["people"].items()},
            meta={k: v for k, v in raw.items()
                  if k not in ("units", "documents", "people")},
            path=path,
        )

    def save(self, path: Path | None = None) -> None:
        path = path or self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            **self.meta,
            "people": {k: v.to_dict() for k, v in self.people.items()},
            "documents": [d.to_dict() for d in self.documents],
            "units": [u.to_dict() for u in self.units],
        }, ensure_ascii=False, indent=1), encoding="utf-8")

    # --- lookup ----------------------------------------------------------
    def unit(self, unit_id: str) -> Unit | None:
        return self._by_id.get(unit_id)

    def doc(self, doc_id: str) -> Document | None:
        return self._docs.get(doc_id)

    def doc_units(self, doc_id: str) -> list[Unit]:
        return self._by_doc.get(doc_id, [])

    def resolve_doc(self, ref: str) -> Document | None:
        """Accept a doc_id, a short code (E07), or a filename stem."""
        if ref in self._docs:
            return self._docs[ref]
        return next((d for d in self.documents
                     if d.meta.get("short") == ref or d.path.endswith(ref) or ref in d.doc_id),
                    None)

    def chronological(self, units: Iterable[Unit] | None = None) -> list[Unit]:
        us = list(units if units is not None else self.units)
        return sorted(us, key=lambda u: (u.date or "9999", u.doc_id, u.seq))

    def stats(self) -> dict:
        kinds: dict[str, int] = {}
        for u in self.units:
            kinds[u.doc_kind] = kinds.get(u.doc_kind, 0) + 1
        dates = [u.date for u in self.units if u.date]
        return {
            "documents": len(self.documents),
            "units": len(self.units),
            "units_by_kind": kinds,
            "people": len(self.people),
            "redacted_units": sum(1 for u in self.units if u.redacted),
            "truncated_units": sum(1 for u in self.units if u.truncated),
            "date_range": [min(dates, default=None), max(dates, default=None)],
            "built_at": self.meta.get("built_at"),
            "corpus_fingerprint": self.meta.get("corpus_fingerprint"),
        }
