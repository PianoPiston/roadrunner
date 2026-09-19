"""Erasure.

"Erase this person from your index, your embeddings and anything you derived or
cached" has three failure modes, and this module is built around avoiding them:

1. **Under-deletion by surface form.** The archive says "Kwame Boateng",
   "Kwame", "Boateng" and "k.boateng@relexsolutions.example". Deleting one
   string leaves the person in the index. We delete every alias the registry
   knows, longest first, diacritic-folded. Two-letter initials match a *speaker*
   but are never redacted from prose, because "KB" also means kilobytes.

2. **No record of the erasure.** Nothing about an erased person is kept --
   no name, no aliases, no audit ledger. Keeping "we deleted Kwame Boateng" is
   still keeping Kwame Boateng. The consequence is deliberate: a rebuild from
   the corpus resurrects them, so a rebuild must be followed by a fresh erasure.

3. **Dishonest reporting.** Deleting a person deletes their ATTRIBUTION, not
   necessarily the facts they reported -- when somebody else restated the same
   figure, the figure survives. The receipt says which is which instead of
   claiming a clean sweep.

Redacted units are kept as tombstones rather than dropped, so a citation to an
erased unit resolves to "withheld" instead of "not found". That distinction is
the difference between an auditable deletion and a hole.

There are no embeddings to purge, by design -- which is a stronger answer to
"erase it from your embeddings" than purging some and hoping.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Literal

from .core import Store, Unit, aliases_for, fold
from .retrieval import FIGURE_RE

Mode = Literal["redact", "purge"]
TOMBSTONE = "[withheld: erased at the request of the data subject]"

# Aliases too short or ambiguous to redact inside free text. They are still used
# to match a speaker, where the field is unambiguous.
_UNSAFE_IN_TEXT = re.compile(r"^[A-ZÅÄÖØÆ]{2,3}$")

DERIVED_DATA_NOTE = ("no vector embeddings exist: this system does not build any. "
                     "Triage results are held in memory per request and never persisted.")


@dataclass
class ErasureReceipt:
    subject: str
    subject_pid: str | None
    aliases_used: list[str]
    mode: str
    erased_at: str
    units_authored_removed: int = 0
    units_mentioning_redacted: int = 0
    mention_replacements: int = 0
    recipient_entries_removed: int = 0
    person_record_removed: bool = False
    documents_affected: list[str] = field(default_factory=list)
    unit_ids_authored: list[str] = field(default_factory=list)
    unit_ids_mentioning: list[str] = field(default_factory=list)
    derived_data: str = DERIVED_DATA_NOTE
    # Facts the subject reported, split by whether anyone else reported them too.
    survived: list[dict] = field(default_factory=list)
    did_not_survive: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _alias_set(store: Store, name: str) -> tuple[str | None, list[str]]:
    """Resolve to a person if known; otherwise synthesise aliases from the name.

    Off-roster people (someone mentioned once, an operator name in a data
    sample) must be erasable too.
    """
    matches = store.registry.search(name)
    if matches:
        return matches[0].pid, store.registry.alias_patterns(matches[0].pid)
    return None, sorted(set(aliases_for(name, [])), key=len, reverse=True)


def _text_aliases(aliases: list[str]) -> list[str]:
    """The aliases safe to redact from running prose."""
    return [a for a in aliases if not _UNSAFE_IN_TEXT.match(a) and len(a) > 2]


def _redact_text(text: str, aliases: list[str]) -> tuple[str, int]:
    n = 0
    out = text
    targets = _text_aliases(aliases)
    for a in targets:
        out, k = re.subn(r"(?<![\w.@-])" + re.escape(a) + r"(?![\w@-])", "[erased]", out, flags=re.I)
        n += k

    # Second pass, diacritic-folded, for spellings the alias list does not carry
    # literally (Sørensen vs Sorensen).
    folded_targets = {fold(a) for a in targets}

    def _fold_sub(m: re.Match[str]) -> str:
        nonlocal n
        if fold(m.group(0)) in folded_targets:
            n += 1
            return "[erased]"
        return m.group(0)

    return re.sub(r"\b[\w'’-]+(?:\s+[\w'’-]+)?\b", _fold_sub, out), n


def _figures_in(text: str) -> set[str]:
    return {m.group("fig").strip().lower() for m in FIGURE_RE.finditer(text)}


def erase_person(store: Store, name: str, mode: Mode = "redact") -> ErasureReceipt:
    """Erase every trace of one person and return an honest receipt.

    Mutates the in-memory index; the caller decides whether to `store.save()`.
    Nothing identifying the subject is written anywhere -- the receipt is
    returned to the requester and never stored. The corpus .txt files are not
    touched: they are the input, not the index.
    """
    pid, aliases = _alias_set(store, name)
    display = store.people[pid].display if pid and pid in store.people else name
    receipt = ErasureReceipt(
        subject=display, subject_pid=pid, aliases_used=aliases, mode=mode,
        erased_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    folded_aliases = {fold(a) for a in aliases}

    # 1. Split units into "authored by the subject" and "merely mentions them".
    authored: list[Unit] = []
    mentioning: list[Unit] = []
    for u in store.units:
        if u.redacted:
            continue
        if ((pid is not None and u.speaker == pid)
                or (u.speaker_display and fold(u.speaker_display) in folded_aliases)):
            authored.append(u)
            continue
        new_text, n = _redact_text(u.text, aliases)
        if n:
            u.text = new_text
            u.redaction_note = (u.redaction_note or "") + f"{n} mention(s) erased. "
            receipt.mention_replacements += n
            mentioning.append(u)
        if u.interrupted_by:      # interruption records carry speaker names too
            cleaned = []
            for iv in u.interrupted_by:
                cv, k = _redact_text(iv, aliases)
                receipt.mention_replacements += k
                cleaned.append(cv)
            u.interrupted_by = cleaned

    # 2. Record which figures the subject was the only source for, BEFORE their
    # text is destroyed.
    erased_figures: dict[str, list[str]] = {}
    for u in authored:
        for f in _figures_in(u.text):
            erased_figures.setdefault(f, []).append(u.unit_id)

    # 3. Tombstone the authored units.
    for u in authored:
        u.text = "" if mode == "purge" else TOMBSTONE
        u.redacted = True
        u.redaction_note = f"authored by an erased data subject; erased {receipt.erased_at}"
        u.speaker = u.speaker_display = u.speaker_org = None
        u.interrupted_by = []
        u.meta = {k: v for k, v in u.meta.items()
                  if k in ("t_start", "t_end", "thread_position", "thread_total")}

    receipt.units_authored_removed = len(authored)
    receipt.units_mentioning_redacted = len(mentioning)
    receipt.unit_ids_authored = [u.unit_id for u in authored]
    receipt.unit_ids_mentioning = [u.unit_id for u in mentioning]
    receipt.documents_affected = sorted({u.doc_id for u in authored + mentioning})

    # 4. Recipient lists, participant lists, and the person record itself.
    for u in store.units:
        if pid and pid in u.recipients:
            u.recipients = [r for r in u.recipients if r != pid]
            receipt.recipient_entries_removed += 1
    for d in store.documents:
        before = len(d.participants)
        # Participants are stored as "Kwame Boateng (RELEX)", so a plain fold()
        # comparison against the alias set never matches. Reuse the redactor:
        # if any alias appears anywhere in the string, the entry is theirs.
        d.participants = [p for p in d.participants if _redact_text(p, aliases)[1] == 0]
        receipt.recipient_entries_removed += before - len(d.participants)
        # A subject line or meeting title can name them too.
        d.title, n_title = _redact_text(d.title, aliases)
        if d.subject:
            d.subject, n_subj = _redact_text(d.subject, aliases)
            receipt.mention_replacements += n_subj
        receipt.mention_replacements += n_title
    if pid and pid in store.people:
        del store.people[pid]
        receipt.person_record_removed = True

    # 5. What survived, and why.
    remaining_figs = _figures_in("\n".join(u.text for u in store.units if not u.redacted))
    for fig, uids in sorted(erased_figures.items()):
        entry = {"figure": fig, "was_in": uids}
        if fig in remaining_figs:
            entry["why"] = ("independently restated elsewhere in the archive by someone "
                            "else, so the fact survives while the attribution does not")
            receipt.survived.append(entry)
        else:
            entry["why"] = "only ever stated by the erased subject, so it is gone"
            receipt.did_not_survive.append(entry)

    store.reindex()
    return receipt


def verify_erasure(store: Store, name: str) -> dict:
    """Independent check: scan the live index for any surviving trace."""
    _, aliases = _alias_set(store, name)
    targets = _text_aliases(aliases)
    folded = {fold(a) for a in targets}

    hits: list[dict] = []
    for u in store.units:
        if u.redacted:
            continue
        for a in targets:
            if re.search(r"(?<![\w.@-])" + re.escape(a) + r"(?![\w@-])", u.text, re.I):
                hits.append({"unit_id": u.unit_id, "alias": a, "excerpt": u.text[:120]})
                break
        if u.speaker_display and fold(u.speaker_display) in folded:
            hits.append({"unit_id": u.unit_id, "alias": u.speaker_display,
                         "excerpt": "speaker field"})

    # Documents carry participant lists, titles and subject lines of their own.
    # Skipping them is how an erasure reports "clean" while the name is still
    # sitting in the index.
    doc_hits: list[dict] = []
    for d in store.documents:
        for label, value in (("participants", " | ".join(d.participants)),
                             ("title", d.title), ("subject", d.subject or "")):
            if value and _redact_text(value, aliases)[1]:
                doc_hits.append({"doc_id": d.doc_id, "field": label, "excerpt": value[:120]})

    people_hits = [pid for pid, p in store.people.items()
                   if fold(p.display) in folded or any(fold(a) in folded for a in p.aliases)]
    return {
        "subject": name,
        "aliases_checked": targets,
        "surviving_text_hits": hits,
        "surviving_document_hits": doc_hits,
        "surviving_person_records": people_hits,
        "clean": not hits and not doc_hits and not people_hits,
    }
