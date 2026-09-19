"""What an answer must look like, and the Python that proves it is honest.

The schema is deliberately opinionated: it forces the model to separate what the
archive says from what it does not, to mark superseded values as superseded, and
to declare where it refused to guess. A free-text answer can hide all three.

Verification is then done in code, not by the model, and enforces two things:

1. A quote is only a quote if it is actually in the cited unit. Checked as a
   substring, whitespace- and case-normalised, with a fuzzy fallback that
   reports "close but not verbatim" rather than passing it off as exact.
2. Citation metadata -- document, date, speaker, position -- is rendered FROM
   the index, never from the model's output. The model supplies a unit id and a
   quote; everything a grader reads is looked up. A model that misremembers a
   date cannot get that error into a citation.

Anything that fails is reported rather than silently dropped, because a
fabricated citation is exactly the failure this challenge is scored on.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import asdict, dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from .core import Store

# ══════════════════════════════════════════════════════════════════════════
# The answer contract (structured output from the analyst model)
# ══════════════════════════════════════════════════════════════════════════

ClaimStatus = Literal["current", "superseded", "disputed", "unverifiable", "not_in_archive"]


class Citation(BaseModel):
    unit_id: str = Field(description="Exact unit id, e.g. E07.m03 or T06.s0008.")
    quote: str = Field(description="Verbatim substring of that unit supporting the claim. Never paraphrase.")


class Claim(BaseModel):
    statement: str = Field(description="One factual assertion.")
    citations: list[Citation] = Field(description="At least one, unless status is not_in_archive.")
    status: ClaimStatus = Field(
        description="current = the latest position in the archive; superseded = true when "
                    "said but later changed; disputed = sources conflict and neither wins; "
                    "unverifiable = stated by someone but never evidenced; "
                    "not_in_archive = the archive does not contain this."
    )
    superseded_by: str = Field(description="unit_id that supersedes this claim, or empty string.")
    as_of: str = Field(description="ISO date this claim was true as of, or empty string.")


class Gap(BaseModel):
    question_part: str = Field(description="The part of the question this concerns.")
    what_is_missing: str = Field(description="What the archive does not contain.")
    nearest_evidence: str = Field(description="unit_id of the closest thing found, or empty string.")
    why_it_cannot_be_answered: str


class Abstention(BaseModel):
    unit_id: str = Field(description="The cut-off or otherwise unusable unit.")
    what_was_being_said: str = Field(description="Only what is literally present before the cut.")
    why_not_completed: str


class Answer(BaseModel):
    answer: str = Field(description="The prose answer. Every factual sentence must correspond to a claim below.")
    claims: list[Claim]
    gaps: list[Gap] = Field(description="Parts of the question the archive does not answer. Empty list if none.")
    abstentions: list[Abstention] = Field(description="Places where evidence was cut off and was NOT completed.")
    confidence: Literal["high", "medium", "low"]
    method_note: str = Field(description="One sentence on how the answer was reached and what was checked.")


# ══════════════════════════════════════════════════════════════════════════
# Verification
# ══════════════════════════════════════════════════════════════════════════

_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS.sub(" ", s).strip().lower()


@dataclass
class VerifiedCitation:
    unit_id: str
    ok: bool
    problem: str | None
    quote: str
    # Everything below is authoritative, read from the index.
    doc_id: str | None = None
    doc_title: str | None = None
    doc_kind: str | None = None
    locator: str | None = None
    speaker: str | None = None
    speaker_org: str | None = None
    date: str | None = None
    internal_recording: bool = False
    truncated_source: bool = False
    match: str = "exact"          # exact | approximate | none
    reference: str = ""           # the citation string a human should read

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class VerificationReport:
    citations: list[VerifiedCitation] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.unsupported_claims and all(c.ok for c in self.citations)

    def summary(self) -> dict:
        return {
            "citations_total": len(self.citations),
            "citations_verified": sum(1 for c in self.citations if c.ok),
            "citations_exact": sum(1 for c in self.citations if c.match == "exact"),
            "citations_approximate": sum(1 for c in self.citations if c.match == "approximate"),
            "citations_failed": [c.unit_id for c in self.citations if not c.ok],
            "unsupported_claims": self.unsupported_claims,
            "warnings": self.warnings,
            "clean": self.ok,
        }


def _best_window_ratio(needle: str, hay: str) -> float:
    """Highest similarity of `needle` against any same-length window of `hay`."""
    if not needle or not hay:
        return 0.0
    n = len(needle)
    if n >= len(hay):
        return difflib.SequenceMatcher(None, needle, hay).ratio()
    best = 0.0
    for i in range(0, len(hay) - n + 1, max(1, n // 4)):
        best = max(best, difflib.SequenceMatcher(None, needle, hay[i:i + n]).ratio())
        if best > 0.98:
            break
    return best


def format_reference(c: VerifiedCitation) -> str:
    """The human-readable citation, built entirely from the index."""
    if c.doc_id is None:
        return f"[UNVERIFIED {c.unit_id}]"
    who = c.speaker or "unattributed"
    if c.speaker_org:
        who += f" ({c.speaker_org})"
    when = (c.date or "undated")[:16].replace("T", " ")
    ref = " — ".join(p for p in [c.doc_id, c.locator or c.unit_id, who, when] if p)
    if c.internal_recording:
        ref += " [internal RELEX recording]"
    if c.truncated_source:
        ref += " [statement cut off]"
    return ref


def verify_citation(store: Store, cit: Citation) -> VerifiedCitation:
    u = store.unit(cit.unit_id)
    if u is None:
        return VerifiedCitation(unit_id=cit.unit_id, ok=False, quote=cit.quote, match="none",
                                problem="no such unit in the index: the citation is fabricated")
    if u.redacted:
        return VerifiedCitation(unit_id=cit.unit_id, ok=False, quote=cit.quote, match="none",
                                problem="unit was withheld under an erasure request "
                                        "and must not be cited")

    nq, nt = _norm(cit.quote), _norm(u.text)
    if nq and nq in nt:
        match, problem, ok = "exact", None, True
    elif (ratio := _best_window_ratio(nq, nt)) >= 0.90:
        match, problem, ok = "approximate", (
            f"quote is not verbatim (similarity {ratio:.2f}); the unit says something close"), True
    else:
        match, problem, ok = "none", "quote does not appear in the cited unit", False

    doc = store.doc(u.doc_id)
    vc = VerifiedCitation(
        unit_id=u.unit_id, ok=ok, problem=problem, quote=cit.quote, match=match,
        doc_id=u.doc_id, doc_title=doc.title if doc else None, doc_kind=u.doc_kind,
        locator=u.locator, speaker=u.speaker_display, speaker_org=u.speaker_org,
        date=u.date, internal_recording=bool(doc and doc.internal),
        truncated_source=u.truncated,
    )
    vc.reference = format_reference(vc)
    return vc


def verify_answer(store: Store, answer: Answer) -> VerificationReport:
    """Check every citation, and flag claims that lean on fragile evidence."""
    rep = VerificationReport()
    seen: set[tuple[str, str]] = set()

    for claim in answer.claims:
        if claim.status != "not_in_archive" and not claim.citations:
            rep.unsupported_claims.append(claim.statement)

        for cit in claim.citations:
            vc = verify_citation(store, cit)
            key = (cit.unit_id, _norm(cit.quote))
            if key not in seen:
                seen.add(key)
                rep.citations.append(vc)
            if vc.truncated_source and claim.status == "current":
                rep.warnings.append(
                    f"{claim.statement[:70]}... rests on {vc.unit_id}, which is cut off "
                    f"mid-sentence; check the claim does not complete it.")
            if vc.internal_recording:
                rep.warnings.append(
                    f"{vc.unit_id} is from an internal RELEX-only recording; the customer "
                    f"never saw it.")

        if claim.superseded_by:
            if store.unit(claim.superseded_by) is None:
                rep.warnings.append(
                    f"superseded_by points at {claim.superseded_by}, which does not exist.")
            elif claim.status == "current":
                rep.warnings.append(
                    f"claim marked current but also names a superseding unit "
                    f"({claim.superseded_by}).")

    for gap in answer.gaps:
        if gap.nearest_evidence and store.unit(gap.nearest_evidence) is None:
            rep.warnings.append(f"gap cites {gap.nearest_evidence}, which does not exist.")

    for ab in answer.abstentions:
        u = store.unit(ab.unit_id)
        if u is None:
            rep.warnings.append(f"abstention cites {ab.unit_id}, which does not exist.")
        elif not u.truncated:
            rep.warnings.append(
                f"abstention on {ab.unit_id}, but the index does not mark it cut off.")
    return rep
