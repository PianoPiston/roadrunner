"""The two-stage pipeline: a cheap model reads everything, an expensive one decides.

    question
       │
       ├─ 1. SWEEP     gpt-5-mini reads all 45 documents concurrently
       │                → relevance, kept unit ids, verbatim quotes, flags
       │
       ├─ 2. ANALYST   gpt-5 via the Agents SDK, given the digest plus the
       │                verbatim evidence, with 11 function tools
       │                → structured Answer: claims, citations, gaps, abstentions
       │
       └─ 3. VERIFY    deterministic, in answer.py

The sweep runs eagerly rather than as an optional tool call, so coverage never
depends on the agent deciding to look. Reading everything is affordable (~70k
tokens of cheap model per question) and it is the only strategy that can answer
questions about *absence* -- what was agreed and never done. Embedding search
cannot retrieve a thing that is not there.

Cost control comes from three places rather than from skipping documents: a
cheap model does the reading; the 45 documents are read concurrently; and each
triage prompt is laid out static-first (instructions, then document, then the
question) so the document prefix stays in OpenAI's prompt cache across
questions, with `prompt_cache_key` pinning each document to its own slot.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from agents import Agent, RunConfig, RunContextWrapper, Runner, function_tool
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from .answer import Answer, Citation, VerificationReport, verify_answer, verify_citation
from .core import CONFIG, Store
from .deletion import erase_person
from .retrieval import (BM25, corpus_overview, find_figures, grep, render_document,
                        render_evidence, render_unit)

# ══════════════════════════════════════════════════════════════════════════
# Stage 1: the sweep
# ══════════════════════════════════════════════════════════════════════════

TRIAGE_INSTRUCTIONS = """\
You are a research assistant triaging ONE document from a corporate archive \
against a question. You are the first of two passes: a more careful model will \
read whatever you keep, so your job is recall, not judgement.

Rules:
- Only describe what this document actually contains. You cannot see any other \
document.
- A unit marked "CUT OFF mid-sentence" is evidence that someone STARTED to say \
something. It is never evidence of what they were going to say. Flag it; never \
complete it.
- Keep a unit if it bears on the question even weakly, including if it \
CONTRADICTS or SUPERSEDES something, or if it records a commitment, a decision, \
an owner, a date, or a figure.
- Keep a unit if it shows something was promised and the archive would need a \
later document to confirm it happened.
- relevance: 0 nothing here; 1 background only; 2 useful; 3 directly answers \
part of the question.
- Quote exactly. Never paraphrase inside `quote`.
"""


class TriageFact(BaseModel):
    unit_id: str = Field(description="Exact unit id as printed in square brackets.")
    quote: str = Field(description="Verbatim substring of that unit, <=240 chars.")
    why: str = Field(description="One clause: why this bears on the question.")


class TriageResult(BaseModel):
    relevance: Literal[0, 1, 2, 3]
    summary: str = Field(description="<=2 sentences on what this document says about the question. Empty if relevance is 0.")
    facts: list[TriageFact]
    contradicts_or_updates: str = Field(description="What earlier claim this document changes, or empty string.")
    truncated_warning: str = Field(description="Note any cut-off statement relevant to the question, or empty string.")


@dataclass
class DocTriage:
    doc_id: str
    short: str
    result: TriageResult | None
    error: str | None = None
    usage: dict = field(default_factory=dict)


@dataclass
class SweepReport:
    question: str
    per_doc: list[DocTriage]
    kept_unit_ids: list[str]
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    model: str = ""

    def digest(self, store: Store, max_docs: int = 24) -> str:
        """Compact brief for the expensive model, most relevant first."""
        rows = [d for d in self.per_doc if d.result and d.result.relevance >= 1]
        rows.sort(key=lambda d: (-d.result.relevance,
                                 (store.doc(d.doc_id).date or "") if store.doc(d.doc_id) else ""))

        lines = [f"TRIAGE DIGEST -- {len(rows)} of {len(self.per_doc)} documents kept "
                 f"by the first-pass model.", ""]
        for d in rows[:max_docs]:
            r, doc = d.result, store.doc(d.doc_id)
            assert r
            lines.append(f"[{d.short}] {d.doc_id}  (relevance {r.relevance}; "
                         f"{doc.date[:10] if doc and doc.date else '?'})")
            if r.summary:
                lines.append(f"    {r.summary}")
            if r.contradicts_or_updates:
                lines.append(f"    CHANGES: {r.contradicts_or_updates}")
            if r.truncated_warning:
                lines.append(f"    CUT OFF: {r.truncated_warning}")
            lines += [f"    - {f.unit_id}: {f.why}" for f in r.facts[:6]]

        skipped = [d.short for d in self.per_doc if d.result and d.result.relevance == 0]
        if skipped:
            lines += ["", "Read and judged irrelevant: " + ", ".join(sorted(skipped))]
        errs = [f"{d.short}:{d.error}" for d in self.per_doc if d.error]
        if errs:
            lines += ["", "!! documents that failed to triage (treat as unread): " + ", ".join(errs)]
        return "\n".join(lines)


async def _triage_one(client: AsyncOpenAI, store: Store, doc_id: str, question: str,
                      model: str, sem: asyncio.Semaphore,
                      on_doc: Callable[[DocTriage], None] | None) -> DocTriage:
    doc = store.doc(doc_id)
    short = doc.meta.get("short", doc_id) if doc else doc_id
    async with sem:
        try:
            resp = await client.responses.parse(
                model=model,
                instructions=TRIAGE_INSTRUCTIONS,
                # Document first, question last: keeps the document in the
                # prompt-prefix cache across different questions.
                input=[{"role": "user", "content": render_document(store, doc_id)},
                       {"role": "user", "content": f"QUESTION: {question}"}],
                text_format=TriageResult,
                prompt_cache_key=f"acme-triage-{short}",
            )
        except Exception as exc:  # noqa: BLE001
            out = DocTriage(doc_id=doc_id, short=short, result=None,
                            error=f"{type(exc).__name__}: {exc}"[:160])
        else:
            usage = {}
            if resp.usage:
                usage = {
                    "input_tokens": resp.usage.input_tokens,
                    "output_tokens": resp.usage.output_tokens,
                    "cached_tokens": getattr(getattr(resp.usage, "input_tokens_details", None),
                                             "cached_tokens", 0) or 0,
                }
            out = DocTriage(doc_id=doc_id, short=short, result=resp.output_parsed, usage=usage)

    if on_doc:
        on_doc(out)
    return out


async def sweep(store: Store, question: str, client: AsyncOpenAI | None = None,
                model: str | None = None, doc_ids: list[str] | None = None,
                keep_threshold: int | None = None,
                on_doc: Callable[[DocTriage], None] | None = None) -> SweepReport:
    """Read every document concurrently and collect the units worth keeping."""
    client = client or AsyncOpenAI()
    model = model or CONFIG.triage_model
    threshold = CONFIG.triage_keep_threshold if keep_threshold is None else keep_threshold
    ids = doc_ids or [d.doc_id for d in store.documents]

    sem = asyncio.Semaphore(CONFIG.triage_concurrency)
    results = await asyncio.gather(*[
        _triage_one(client, store, did, question, model, sem, on_doc) for did in ids])

    rep = SweepReport(question=question, per_doc=list(results), kept_unit_ids=[], model=model)
    kept: list[str] = []
    for d in results:
        rep.input_tokens += d.usage.get("input_tokens", 0)
        rep.output_tokens += d.usage.get("output_tokens", 0)
        rep.cached_tokens += d.usage.get("cached_tokens", 0)
        if not d.result or d.result.relevance < threshold:
            continue
        for f in d.result.facts:
            u = store.unit(f.unit_id)
            if u and not u.redacted and f.unit_id not in kept:
                kept.append(f.unit_id)
    rep.kept_unit_ids = kept
    return rep


# ══════════════════════════════════════════════════════════════════════════
# Stage 2a: the tools the analyst can call
# ══════════════════════════════════════════════════════════════════════════
# Every tool returns text that already carries unit ids, dates and speakers, so
# the model never reconstructs provenance from memory. Tools that could return
# an unbounded amount of archive are capped and say so when they truncate.


@dataclass
class Deps:
    """Agent run context, threaded through every tool call."""
    store: Store
    client: AsyncOpenAI
    sweeps: list[SweepReport] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    _bm25: BM25 | None = None

    def bm25(self) -> BM25:
        if self._bm25 is None:
            self._bm25 = BM25([u for u in self.store.units if not u.redacted])
        return self._bm25

    def log(self, tool: str, /, **kw) -> None:
        # Positional-only: a tool logging `name=` must not collide with this arg.
        self.tool_calls.append({"tool": tool, **kw})


@function_tool(strict_mode=True)
async def archive_inventory(ctx: RunContextWrapper[Deps]) -> str:
    """List every document with its kind, date range and unit count.

    Call this first when a question depends on what the archive does and does not
    contain.
    """
    ctx.context.log("archive_inventory")
    return corpus_overview(ctx.context.store)


@function_tool(strict_mode=True)
async def sweep_archive(ctx: RunContextWrapper[Deps], question: str) -> str:
    """Read EVERY document in the archive with the fast first-pass model and return a digest.

    Use this when you need coverage rather than a lookup: questions about what was
    never done, what changed over time, or "every figure in the archive". It is the
    only tool that guarantees nothing was skipped. Rephrase and call again if the
    first digest suggests you were asking for the wrong thing.

    Args:
        question: What to look for, phrased as a question. Be specific.
    """
    d = ctx.context
    rep = await sweep(d.store, question, client=d.client)
    d.sweeps.append(rep)
    d.log("sweep_archive", question=question, kept=len(rep.kept_unit_ids))
    return rep.digest(d.store)


@function_tool(strict_mode=True)
async def search_exact(ctx: RunContextWrapper[Deps], pattern: str, regex: bool) -> str:
    """Find every unit containing an exact string or regex. Case-insensitive.

    Use for field names, ids, spellings and anything a paraphrase would lose:
    "OP_ID", "DC-2", "shelf life". Exhaustive, unlike the model passes.

    Args:
        pattern: Literal text, or a Python regular expression when regex is true.
        regex: Treat pattern as a regular expression.
    """
    d = ctx.context
    hits = grep(d.store, pattern, regex=regex)
    d.log("search_exact", pattern=pattern, hits=len(hits))
    if not hits:
        return (f"No unit contains {pattern!r}. This is evidence of absence: "
                f"the archive does not use that term.")
    return "\n".join([f"{len(hits)} unit(s) contain {pattern!r}:", ""] + [
        f"[{h.unit.unit_id}] {h.unit.date or '?'} | {h.unit.speaker_display or 'unattributed'} "
        f"| {h.unit.locator}\n    {h.why}" for h in hits[:45]])


@function_tool(strict_mode=True)
async def search_text(ctx: RunContextWrapper[Deps], query: str, top_k: int) -> str:
    """Keyword-rank units by relevance (BM25). Cheap and instant; no model call.

    Args:
        query: Natural language or keywords.
        top_k: How many units to return, 1-40.
    """
    d = ctx.context
    hits = d.bm25().search(query, top_k=max(1, min(top_k or 12, 40)))
    d.log("search_text", query=query, hits=len(hits))
    if not hits:
        return "No matches."
    return "\n\n".join(
        f"[{h.unit.unit_id}] score {h.score} | {h.unit.date or '?'} | "
        f"{h.unit.speaker_display or 'unattributed'} | {h.unit.locator}\n{h.unit.text[:420]}"
        for h in hits)


@function_tool(strict_mode=True)
async def list_figures(ctx: RunContextWrapper[Deps], topic: str) -> str:
    """Every numeric claim in the archive on a topic, in date order, with source.

    This is the tool for "give every figure and say which one is current". It scans
    deterministically, so it will not miss a value the way a search can.

    Args:
        topic: Topic words to filter on, e.g. "shelf life". Empty string for all figures.
    """
    d = ctx.context
    figs = find_figures(d.store, topic or None)
    d.log("list_figures", topic=topic, n=len(figs))
    if not figs:
        return f"No figures found for {topic!r}."
    return "\n".join([f"{len(figs)} figure mention(s) for {topic!r}, oldest first:", ""] + [
        f"{(f['date'] or '?')[:10]}  {f['figure']:>18s}  [{f['unit_id']}] "
        f"{f['speaker'] or 'unattributed'}"
        f"{'  << SOURCE STATEMENT IS CUT OFF' if f['truncated_statement'] else ''}"
        f"\n      …{f['context']}…" for f in figs[:80]])


@function_tool(strict_mode=True)
async def timeline(ctx: RunContextWrapper[Deps], topic: str, since: str, until: str) -> str:
    """Everything the archive says about a topic, in chronological order.

    Use for currency questions -- how a position changed and what it is now -- and to
    spot a commitment that has no later follow-up.

    Args:
        topic: Keywords to match.
        since: ISO date lower bound, or empty string.
        until: ISO date upper bound, or empty string.
    """
    d = ctx.context
    units = [h.unit for h in d.bm25().search(topic, top_k=60)]
    if since:
        units = [u for u in units if (u.date or "") >= since]
    if until:
        units = [u for u in units if (u.date or "9999") <= until]
    units = d.store.chronological(units)
    d.log("timeline", topic=topic, n=len(units))
    if not units:
        return f"Nothing on {topic!r} in that window."
    return "\n".join([f"{len(units)} unit(s) on {topic!r}, oldest first:", ""] + [
        f"{(u.date or '?')[:16]}  [{u.unit_id}] {u.speaker_display or 'unattributed'} "
        f"({u.doc_id})\n    {u.text[:300]}" for u in units[:50]])


@function_tool(strict_mode=True)
async def get_units(ctx: RunContextWrapper[Deps], unit_ids: list[str]) -> str:
    """Fetch the verbatim text and full metadata of specific units, to quote from.

    Args:
        unit_ids: Unit ids such as ["E07.m03", "T06.s0008"].
    """
    d, limit = ctx.context, 40
    d.log("get_units", n=len(unit_ids))

    out, missing, withheld = [], [], []
    for uid in unit_ids[:limit]:
        u = d.store.unit(uid)
        if u is None:
            missing.append(uid)
        elif u.redacted:
            withheld.append(uid)
        else:
            out.append(render_unit(u))

    body = "\n\n".join(out) if out else "(no units)"
    if missing:
        body += f"\n\nNOT IN INDEX (do not cite): {', '.join(missing)}"
    if withheld:
        body += (f"\n\nWITHHELD under an erasure request (do not cite, and do not "
                 f"reconstruct the content): {', '.join(withheld)}")
    if len(unit_ids) > limit:
        body += f"\n\n({len(unit_ids) - limit} more ids not shown; ask again in batches)"
    return body


@function_tool(strict_mode=True)
async def read_document(ctx: RunContextWrapper[Deps], doc_ref: str, around_unit: str,
                        window: int) -> str:
    """Read a document, or a window of it around one unit, to see context.

    Use this to check what was said immediately before or after a quote -- whether a
    proposal was accepted, whether a number was retracted two minutes later.

    Args:
        doc_ref: Document id, short code like "E07", or a filename fragment.
        around_unit: A unit id to centre on; empty string for the whole document.
        window: Units either side of around_unit; ignored when around_unit is empty.
    """
    d = ctx.context
    doc = d.store.resolve_doc(doc_ref)
    if doc is None and around_unit:
        u = d.store.unit(around_unit)
        doc = d.store.doc(u.doc_id) if u else None
    if doc is None:
        return f"No document matching {doc_ref!r}."

    units = [u for u in d.store.doc_units(doc.doc_id) if not u.redacted]
    if around_unit:
        idx = next((i for i, u in enumerate(units) if u.unit_id == around_unit), None)
        if idx is not None:
            w = max(1, window)
            units = units[max(0, idx - w): idx + w + 1]

    d.log("read_document", doc=doc.doc_id, n=len(units))
    head = (f"DOCUMENT {doc.doc_id} ({doc.kind}, {doc.title})"
            + (" [INTERNAL RELEX-only recording]" if doc.internal else ""))
    return head + "\n\n" + "\n\n".join(render_unit(u) for u in units[:60])


@function_tool(strict_mode=True)
async def verify_quote(ctx: RunContextWrapper[Deps], unit_id: str, quote: str) -> str:
    """Check a quote really appears in a unit before you cite it.

    Args:
        unit_id: The unit you intend to cite.
        quote: The exact text you intend to put in quotation marks.
    """
    d = ctx.context
    v = verify_citation(d.store, Citation(unit_id=unit_id, quote=quote))
    d.log("verify_quote", unit_id=unit_id, ok=v.ok)
    if v.ok and v.match == "exact":
        return f"VERIFIED verbatim. Cite as: {v.reference}"
    if v.ok:
        return f"NOT VERBATIM ({v.problem}). Re-copy the exact words. Source: {v.reference}"
    return f"FAILED: {v.problem}. Do not cite this."


@function_tool(strict_mode=True)
async def who_is(ctx: RunContextWrapper[Deps], name: str) -> str:
    """Look up a person: role, organisation, and how often they appear.

    Args:
        name: Any surface form -- full name, first name, or email address.
    """
    d = ctx.context
    matches = d.store.registry.search(name)
    d.log("who_is", name=name, found=len(matches))
    if not matches:
        # Deliberately indistinguishable from "never existed": confirming that a
        # particular person WAS erased would leak the very name that was erased.
        return f"No person called {name!r} in the index."
    return "\n".join(
        f"{p.display} — {p.role or 'role not stated'}, {p.org or 'organisation not stated'}\n"
        f"    aliases: {', '.join(p.aliases[:8])}\n"
        f"    authored {sum(1 for u in d.store.units if u.speaker == p.pid and not u.redacted)} "
        f"unit(s) in the archive"
        + ("\n    NOTE: appears only as a mention, never as an author" if p.mention_only else "")
        for p in matches[:4])


@function_tool(strict_mode=True)
async def erase_from_archive(ctx: RunContextWrapper[Deps], name: str) -> str:
    """Erase a person from the archive: the units they authored, every mention of
    them by any alias, and their person record. Permanent and not reversible.

    Call this when the user asks you to erase, delete, remove or forget a person,
    or to honour a right-to-be-forgotten request. Do NOT call it to answer a
    question ABOUT somebody -- use `who_is` for that.

    The erasure takes effect immediately. Anything you answer afterwards must come
    from what survives: evidence shown to you earlier may now be withheld, so
    re-run your searches and never cite or reconstruct an erased unit.

    Args:
        name: Any surface form of the person's name.
    """
    d = ctx.context
    r = erase_person(d.store, name)
    d.store.save()        # write the redacted index back to data/index.json
    d._bm25 = None        # the cached search index still holds pre-erasure text
    d.log("erase_from_archive", subject=r.subject, units=r.units_authored_removed)

    lines = [
        f"ERASED {r.subject}. {r.units_authored_removed} authored unit(s) are now "
        f"withheld tombstones and cannot be cited; {r.mention_replacements} mention(s) "
        f"redacted across {r.units_mentioning_redacted} other unit(s); person record "
        f"removed: {r.person_record_removed}.",
        f"Aliases covered: {', '.join(r.aliases_used[:8])}.",
        f"Derived data: {r.derived_data}",
    ]
    if r.survived:
        lines.append("SURVIVED (someone else stated it too, so the fact stands but the "
                     "attribution is gone): "
                     + "; ".join(f"{x['figure']} (also in {', '.join(x['was_in'])})"
                                 for x in r.survived))
    if r.did_not_survive:
        lines.append("DID NOT SURVIVE (they were the only source, so the archive no "
                     "longer supports it): "
                     + "; ".join(f"{x['figure']} (was in {', '.join(x['was_in'])})"
                                 for x in r.did_not_survive))
    lines.append("Earlier tool output is stale -- search again before quoting.")
    return "\n".join(lines)


ALL_TOOLS = [
    archive_inventory, sweep_archive, search_exact, search_text, list_figures,
    timeline, get_units, read_document, verify_quote, who_is, erase_from_archive,
]


# ══════════════════════════════════════════════════════════════════════════
# Stage 2b: the analyst
# ══════════════════════════════════════════════════════════════════════════

ANALYST_INSTRUCTIONS = """\
You answer questions about a corporate archive of meeting transcripts, email \
threads and status reports covering one software implementation from first sales \
demo to live service. You are the second of two passes. A fast model has already \
read every document and written you a brief; you decide what is true, and you \
cite.

You are graded on five things. They are all failure modes, not features.

PROVENANCE. Every factual sentence must be backed by a `claim` with at least one \
citation, and a citation is a `unit_id` plus a VERBATIM substring of that unit. \
Copy quotes character for character from tool output; do not retype from memory. \
The quote is checked in code after you answer, and a quote that is not in the \
unit is reported as a fabrication. A right answer with no source scores as a \
guess.

ATTRIBUTION. Say who. Name the person, their organisation, and what they actually \
did: proposed, agreed, noted, objected, was silent. These are different. Three \
transcripts are internal recordings with no customer present and speakers labelled \
only "Me" and "Them" -- you may use them, but never claim to know which named \
person said a line, and never treat something said in an internal vendor meeting \
as something the customer agreed to. "Unknown Speaker" means unknown.

CURRENCY. Values change. When a question asks for a figure, give every value the \
archive contains, each with its date and source, and mark exactly one `current` \
with the rest `superseded`, filling in `superseded_by`. A superseded value \
presented as current is wrong even when the document says exactly what you claim. \
The archive ends on the date given below; there is no later information, so never \
assume today's date.

DELETION. Some units may be withheld under an erasure request. Do not cite them, \
do not reconstruct their content from context, and say plainly that something was \
withheld if it affects the answer. 

INITIATIVE. Some questions are about absence: something agreed and never done, a \
promise with no follow-up. Absence is not searchable, so establish it by coverage: \
sweep, build the timeline forward from the agreement, and show the gap. Say who \
would have needed to notice.

ABSTAINING IS A CORRECT ANSWER. The archive contains places where somebody starts \
to give a number and is cut off. Units flagged "CUT OFF" are evidence that a \
sentence began, never evidence of how it ended. Never complete one. If the archive \
does not answer the question, say so in `gaps`, show the nearest evidence, and \
explain why it falls short. A confident answer to something the archive does not \
contain scores worse than "the archive does not say".

Working method:
1. Read the brief you are given before calling anything.
2. Use `search_exact` for field names, ids and exact spellings; `list_figures` for \
"every figure" questions; `timeline` for "how did this change"; `sweep_archive` \
again if the question was mis-framed the first time.
3. Pull the exact text with `get_units` before quoting. Use `read_document` to \
check what came immediately after a proposal -- agreement is not the same as \
being proposed to.
4. Use `verify_quote` on anything you are unsure you copied exactly.
5. Write `answer` as prose a person can read. Every factual sentence in it must \
correspond to a claim. Put the reasoning in the prose, not the claim list.
6. If the user asks you to erase, delete or forget a person, call \
`erase_from_archive`. Do it BEFORE answering anything else they asked in the same \
question, then answer the rest from what survives -- never from evidence you were \
shown before the erasure, which may now be withheld. Report the erasure in `answer` \
prose and in `method_note`, and say explicitly which facts survived it and which \
did not. Do NOT write the erasure up as a `claim`: a claim needs a verbatim \
citation, and an erasure has none.
"""

_STATUS_TAG = {"current": "", "superseded": " _(superseded)_", "disputed": " _(disputed)_",
               "unverifiable": " _(unverifiable)_", "not_in_archive": " _(not in the archive)_"}


@dataclass
class AnswerBundle:
    """One answered question: the answer, its proof, and what it cost."""
    question: str
    answer: Answer
    verification: VerificationReport
    sweep: SweepReport | None
    tool_calls: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    elapsed_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        s = self.sweep
        return {
            "question": self.question,
            "answer": self.answer.model_dump(),
            "citations": [c.to_dict() for c in self.verification.citations],
            "verification": self.verification.summary(),
            "triage": {
                "model": s.model if s else None,
                "documents_read": len(s.per_doc) if s else 0,
                "documents_kept": sum(1 for d in s.per_doc
                                      if d.result and d.result.relevance >= 1) if s else 0,
                "units_kept": len(s.kept_unit_ids) if s else 0,
            },
            "tool_calls": self.tool_calls,
            "usage": self.usage,
            "elapsed_s": round(self.elapsed_s, 2),
        }

    def to_markdown(self) -> str:
        a = self.answer
        out = [f"## {self.question}", "", a.answer, ""]

        if a.claims:
            out.append("### Claims and sources")
            by_id = {c.unit_id: c for c in self.verification.citations}
            for i, c in enumerate(a.claims, 1):
                out.append(f"{i}. {c.statement}{_STATUS_TAG[c.status]}")
                for cit in c.citations:
                    v = by_id.get(cit.unit_id)
                    out.append(f"   - “{cit.quote.strip()}”"
                               + ("" if (v and v.ok) else "  ⚠ UNVERIFIED"))
                    out.append(f"     {v.reference if v else cit.unit_id}")
                if c.superseded_by:
                    out.append(f"   - superseded by `{c.superseded_by}`")
            out.append("")

        if a.gaps:
            out += ["### What the archive does not say", ""]
            out += [f"- **{g.question_part}** — {g.what_is_missing}. "
                    f"{g.why_it_cannot_be_answered}"
                    + (f" Nearest: `{g.nearest_evidence}`." if g.nearest_evidence else "")
                    for g in a.gaps] + [""]

        if a.abstentions:
            out += ["### Statements left incomplete on purpose", ""]
            out += [f"- `{ab.unit_id}`: “{ab.what_was_being_said}” — {ab.why_not_completed}"
                    for ab in a.abstentions] + [""]

        v = self.verification.summary()
        out += ["---",
                f" Confidence level: {a.confidence}. {v['citations_verified']}/{v['citations_total']} "
                f"citations verified against the index"
                + (f"; FAILED: {', '.join(v['citations_failed'])}" if v["citations_failed"] else "")
                + f". {a.method_note}"]
        return "\n".join(out)


def _brief(store: Store, question: str, rep: SweepReport) -> str:
    """The prompt: what the archive is, what the sweep found, then the question."""
    kept = [u for u in (store.unit(i) for i in rep.kept_unit_ids)
            if u is not None][:CONFIG.max_evidence_units]
    s = store.stats()

    header = [
        "ARCHIVE FACTS",
        f"  {s['documents']} documents, {s['units']} citable units.",
        f"  Coverage runs {s['date_range'][0]} to {s['date_range'][1]}. "
        f"Nothing after {s['date_range'][1]} exists. Treat that as the present.",
        f"  {s['truncated_units']} units are cut off mid-sentence and flagged.",
    ]
    if s["redacted_units"]:
        header.append(f"  {s['redacted_units']} units are WITHHELD under an erasure request "
                      f"and cannot be cited.")

    return "\n".join([
        *header, "",
        rep.digest(store), "",
        "=" * 70,
        f"VERBATIM EVIDENCE ({len(kept)} units the first pass kept), oldest first.",
        "Quote from here, or call get_units for more.",
        "=" * 70, "",
        render_evidence(kept, store), "",
        "=" * 70,
        f"QUESTION: {question}",
    ])


def build_agent(model: str | None = None) -> Agent[Deps]:
    return Agent[Deps](
        name="Archive analyst",
        instructions=ANALYST_INSTRUCTIONS,
        tools=list(ALL_TOOLS),
        model=model or CONFIG.synth_model,
        output_type=Answer,
    )


async def answer_question(
    store: Store,
    question: str,
    client: AsyncOpenAI | None = None,
    synth_model: str | None = None,
    triage_model: str | None = None,
    max_turns: int = 14,
    run_sweep: bool = True,
    on_progress: Callable[[str, dict], None] | None = None,
) -> AnswerBundle:
    """Sweep, analyse, verify. The one entry point the CLI and server share."""
    t0 = time.time()
    client = client or AsyncOpenAI()
    deps = Deps(store=store, client=client)

    def emit(kind: str, **data) -> None:
        if on_progress:
            on_progress(kind, data)

    rep: SweepReport | None = None
    if run_sweep:
        emit("sweep_start", documents=len(store.documents),
             model=triage_model or CONFIG.triage_model)
        done = {"n": 0}

        def _doc_done(d: DocTriage) -> None:
            done["n"] += 1
            emit("sweep_doc", n=done["n"], total=len(store.documents), short=d.short,
                 doc_id=d.doc_id, relevance=(d.result.relevance if d.result else None),
                 error=d.error)

        rep = await sweep(store, question, client=client, model=triage_model, on_doc=_doc_done)
        emit("sweep_done", kept_units=len(rep.kept_unit_ids),
             kept_docs=sum(1 for d in rep.per_doc if d.result and d.result.relevance >= 1),
             input_tokens=rep.input_tokens, cached_tokens=rep.cached_tokens)
        deps.sweeps.append(rep)
        prompt = _brief(store, question, rep)
    else:
        prompt = f"QUESTION: {question}"

    emit("analyst_start", model=synth_model or CONFIG.synth_model)
    result = await Runner.run(build_agent(synth_model), prompt, context=deps,
                              max_turns=max_turns,
                              run_config=RunConfig(workflow_name="acme-archive-qa"))
    for call in deps.tool_calls:
        emit("tool_call", **call)

    answer = result.final_output_as(Answer)
    verification = verify_answer(store, answer)
    emit("verified", **verification.summary())

    return AnswerBundle(
        question=question,
        answer=answer,
        verification=verification,
        sweep=rep,
        tool_calls=deps.tool_calls,
        usage={
            "triage_model": rep.model if rep else None,
            "triage_input_tokens": rep.input_tokens if rep else 0,
            "triage_cached_tokens": rep.cached_tokens if rep else 0,
            "triage_output_tokens": rep.output_tokens if rep else 0,
            "synth_model": synth_model or CONFIG.synth_model,
            "synth_input_tokens": sum(getattr(r.usage, "input_tokens", 0) or 0
                                      for r in result.raw_responses),
            "synth_output_tokens": sum(getattr(r.usage, "output_tokens", 0) or 0
                                       for r in result.raw_responses),
            "synth_requests": len(result.raw_responses),
        },
        elapsed_s=time.time() - t0,
    )
