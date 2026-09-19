"""Transports: the CLI and the HTTP API, both thin wrappers over the same core.

Nothing in this file decides anything. Both entry points load the index and
hand the question to `agent.answer_question`.

    acme-agent build | stats | ask | practice | erase | verify-erasure
                     | grep | figures | serve

`grep` and `figures` make no model calls at all and are instant -- useful while
debugging and useful in a demo.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from .agent import answer_question
from .answer import Citation, verify_citation
from .core import CONFIG, Store
from .deletion import erase_person, verify_erasure
from .ingest import build_index
from .retrieval import find_figures, grep

PRACTICE = {
    "P1": "What did the master-data assessment report as complete in September 2024? Give every figure and the document each comes from.",
    "P2": "What service levels were agreed for ordering, and in which meeting?",
    "P3": "Who proposed removing the operator ID field from the data extract, who agreed, and had it already been sent anywhere by then?",
    "P4": "Did Acme sign off UAT for the programme? Quote the scope of what was actually signed, and name who signed it.",
    "P5": "What proportion of articles had shelf-life data populated? Give every figure in the archive with its date and source, and say which one is current.",
    "P6": "Is bakery inside the fresh workstream? Show how the answer changed over time and what it is now.",
    "P8": "Find one thing in the archive that was agreed and then never done. Show the trail from the agreement to the present, and say who would have needed to notice.",
    "P9": "The weekly status reports say the nightly article extract completed with no errors. Is that true? Answer the question the reports are actually evidence for, and say what they are not evidence for.",
}


def load_store() -> Store:
    """Load the index, building it first if it is missing."""
    if not CONFIG.index_path.exists():
        print("index missing, building...", file=sys.stderr)
        build_index()
    return Store.load()


# ══════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════

def _progress(kind: str, data: dict) -> None:
    """Live stage reporting on stderr, so stdout stays pipeable."""
    if kind == "sweep_start":
        print(f"  sweeping {data['documents']} documents with {data['model']}...", file=sys.stderr)
    elif kind == "sweep_doc":
        print(str(data.get("relevance") or "."), end="", flush=True, file=sys.stderr)
    elif kind == "sweep_done":
        print(f"\n  kept {data['kept_docs']} documents / {data['kept_units']} units "
              f"({data['input_tokens']} in, {data['cached_tokens']} cached)", file=sys.stderr)
    elif kind == "analyst_start":
        print(f"  analyst: {data['model']}", file=sys.stderr)
    elif kind == "tool_call":
        print(f"    tool: {data.get('tool')}", file=sys.stderr)
    elif kind == "verified":
        print(f"  citations {data['citations_verified']}/{data['citations_total']} verified"
              + (f", FAILED {data['citations_failed']}" if data["citations_failed"] else ""),
              file=sys.stderr)


def _cmd_build(args) -> int:
    """Rebuild from the corpus. NOTE: this resurrects anyone previously erased --
    no record of an erasure is kept, so it must be re-applied by hand."""
    build_index(Path(args.corpus) if args.corpus else None)
    print(json.dumps(Store.load().stats(), indent=1))
    return 0


def _cmd_stats(args) -> int:
    print(json.dumps(load_store().stats(), indent=1))
    return 0


def _cmd_ask(args) -> int:
    store = load_store()
    bundle = asyncio.run(answer_question(
        store, args.question, synth_model=args.synth_model, triage_model=args.triage_model,
        run_sweep=not args.no_sweep, on_progress=None if args.quiet else _progress))
    print(json.dumps(bundle.to_dict(), ensure_ascii=False, indent=1) if args.json
          else bundle.to_markdown())
    if args.out:
        Path(args.out).write_text(bundle.to_markdown(), encoding="utf-8")
        print(f"\nwritten to {args.out}", file=sys.stderr)
    return 0 if bundle.verification.ok else 2


def _cmd_practice(args) -> int:
    store = load_store()
    outdir = Path(args.out_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    parts = []
    for k in (args.only.split(",") if args.only else list(PRACTICE)):
        if k not in PRACTICE:
            print(f"unknown question {k}", file=sys.stderr)
            continue
        print(f"\n=== {k} ===", file=sys.stderr)
        bundle = asyncio.run(answer_question(
            store, PRACTICE[k], synth_model=args.synth_model, triage_model=args.triage_model,
            on_progress=None if args.quiet else _progress))
        md = f"# {k}\n\n" + bundle.to_markdown()
        (outdir / f"{k}.md").write_text(md, encoding="utf-8")
        (outdir / f"{k}.json").write_text(
            json.dumps(bundle.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        parts.append(md)

    (outdir / "ALL.md").write_text("\n\n---\n\n".join(parts), encoding="utf-8")
    print(f"\nwritten to {outdir}/", file=sys.stderr)
    return 0


def _cmd_erase(args) -> int:
    store = load_store()
    receipt = erase_person(store, args.name, mode=args.mode)
    store.save()
    print(json.dumps(receipt.to_dict(), ensure_ascii=False, indent=1))
    print("\nindependent verification:")
    print(json.dumps(verify_erasure(store, args.name), ensure_ascii=False, indent=1))
    return 0


def _cmd_verify_erasure(args) -> int:
    print(json.dumps(verify_erasure(load_store(), args.name), ensure_ascii=False, indent=1))
    return 0


def _cmd_grep(args) -> int:
    for h in grep(load_store(), args.pattern, regex=args.regex):
        print(f"[{h.unit.unit_id}] {h.unit.date or '?'} {h.unit.speaker_display or '-'} "
              f"| {h.unit.locator}\n    {h.why}")
    return 0


def _cmd_figures(args) -> int:
    for f in find_figures(load_store(), args.topic or None):
        print(f"{(f['date'] or '?')[:10]}  {f['figure']:>18s}  [{f['unit_id']}] "
              f"{f['speaker'] or '-'}{'  << CUT OFF' if f['truncated_statement'] else ''}\n"
              f"      …{f['context']}…")
    return 0


def _cmd_serve(args) -> int:
    import uvicorn
    uvicorn.run("acme_agent.app:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="acme-agent", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="parse the corpus into the index")
    b.add_argument("--corpus", default=None)
    b.set_defaults(fn=_cmd_build)

    sub.add_parser("stats", help="show index statistics").set_defaults(fn=_cmd_stats)

    a = sub.add_parser("ask", help="answer one question")
    a.add_argument("question")
    a.add_argument("--json", action="store_true")
    a.add_argument("--out", default=None, help="also write markdown here")
    a.add_argument("--synth-model", default=None)
    a.add_argument("--triage-model", default=None)
    a.add_argument("--no-sweep", action="store_true",
                   help="skip the cheap full-corpus pass (tools only)")
    a.add_argument("--quiet", action="store_true")
    a.set_defaults(fn=_cmd_ask)

    pr = sub.add_parser("practice", help="answer the practice questions and write them out")
    pr.add_argument("--out-dir", default="answers")
    pr.add_argument("--only", default=None, help="comma separated, e.g. P1,P5")
    pr.add_argument("--synth-model", default=None)
    pr.add_argument("--triage-model", default=None)
    pr.add_argument("--quiet", action="store_true")
    pr.set_defaults(fn=_cmd_practice)

    e = sub.add_parser("erase", help="erase a person from the index")
    e.add_argument("name")
    e.add_argument("--mode", choices=["redact", "purge"], default="redact")
    e.set_defaults(fn=_cmd_erase)

    v = sub.add_parser("verify-erasure", help="scan the live index for surviving traces")
    v.add_argument("name")
    v.set_defaults(fn=_cmd_verify_erasure)

    g = sub.add_parser("grep", help="exact search, no model calls")
    g.add_argument("pattern")
    g.add_argument("--regex", action="store_true")
    g.set_defaults(fn=_cmd_grep)

    f = sub.add_parser("figures", help="every figure on a topic, dated")
    f.add_argument("topic", nargs="?", default="")
    f.set_defaults(fn=_cmd_figures)

    s = sub.add_parser("serve", help="run the HTTP API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--reload", action="store_true")
    s.set_defaults(fn=_cmd_serve)

    args = p.parse_args(argv)
    return args.fn(args)


# ══════════════════════════════════════════════════════════════════════════
# HTTP API
# ══════════════════════════════════════════════════════════════════════════
# The index is loaded once at startup and held in memory. Mutating endpoints
# (erase, rebuild) take a lock, because an erasure that half-applied while a
# question was being answered would be worse than no erasure at all.

STATE: dict[str, Any] = {}
LOCK = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    STATE["store"] = load_store()
    try:
        STATE["client"] = AsyncOpenAI()
    except Exception as exc:  # noqa: BLE001
        # No API key: index, search and erasure endpoints still work.
        STATE["client"] = None
        STATE["client_error"] = str(exc)
    yield
    STATE.clear()


app = FastAPI(title="Acme archive agent", version="0.1.0", lifespan=lifespan)


def store() -> Store:
    if (s := STATE.get("store")) is None:
        raise HTTPException(503, "index not loaded")
    return s


def client() -> AsyncOpenAI:
    if (c := STATE.get("client")) is None:
        raise HTTPException(503, f"OpenAI client unavailable: "
                                 f"{STATE.get('client_error', 'no API key')}. "
                                 f"Set OPENAI_API_KEY in .env.")
    return c


class AskRequest(BaseModel):
    question: str
    synth_model: str | None = None
    triage_model: str | None = None
    run_sweep: bool = True
    max_turns: int = 14
    format: Literal["json", "markdown"] = "json"


class EraseRequest(BaseModel):
    name: str = Field(description="Any surface form of the person's name.")
    mode: Literal["redact", "purge"] = "redact"


class VerifyRequest(BaseModel):
    unit_id: str
    quote: str


# --- read ----------------------------------------------------------------
@app.get("/health")
async def health() -> dict:
    return {"ok": "store" in STATE, "index": str(CONFIG.index_path),
            "openai_ready": STATE.get("client") is not None,
            "triage_model": CONFIG.triage_model, "synth_model": CONFIG.synth_model}


@app.get("/stats")
async def stats() -> dict:
    return store().stats()


@app.get("/documents")
async def documents() -> list[dict]:
    return [d.to_dict() for d in store().documents]


@app.get("/documents/{doc_id:path}")
async def document(doc_id: str) -> dict:
    s = store()
    d = s.resolve_doc(doc_id)
    if not d:
        raise HTTPException(404, f"no document {doc_id!r}")
    return {"document": d.to_dict(), "units": [u.to_dict() for u in s.doc_units(d.doc_id)]}


@app.get("/units/{unit_id}")
async def unit(unit_id: str) -> dict:
    u = store().unit(unit_id)
    if not u:
        raise HTTPException(404, f"no unit {unit_id!r}")
    if u.redacted:
        # 410 Gone, not 404: "withheld" and "never existed" are different facts.
        raise HTTPException(410, {"unit_id": unit_id, "withheld": True,
                                  "reason": u.redaction_note})
    return u.to_dict()


@app.get("/people")
async def people() -> list[dict]:
    return [p.to_dict() for p in store().people.values()]


@app.get("/grep")
async def grep_units(pattern: str, regex: bool = False, limit: int = 100) -> dict:
    """Exact or regex search. No model calls, so the UI can call it per keystroke."""
    hits = grep(store(), pattern, regex=regex, limit=limit)
    return {"pattern": pattern, "count": len(hits), "hits": [
        {"unit_id": h.unit.unit_id, "doc_id": h.unit.doc_id, "date": h.unit.date,
         "speaker": h.unit.speaker_display, "locator": h.unit.locator,
         "truncated": h.unit.truncated, "context": h.why} for h in hits]}


@app.get("/figures")
async def figures(topic: str = "", limit: int = 200) -> dict:
    """Every dated numeric claim on a topic, oldest first. No model calls."""
    figs = find_figures(store(), topic or None, limit=limit)
    return {"topic": topic, "count": len(figs), "figures": figs}


@app.post("/verify")
async def verify(req: VerifyRequest) -> dict:
    return verify_citation(store(), Citation(unit_id=req.unit_id, quote=req.quote)).to_dict()


# --- ask -----------------------------------------------------------------
@app.post("/ask")
async def ask(req: AskRequest) -> Any:
    bundle = await answer_question(
        store(), req.question, client=client(), synth_model=req.synth_model,
        triage_model=req.triage_model, max_turns=req.max_turns, run_sweep=req.run_sweep)
    return {"markdown": bundle.to_markdown()} if req.format == "markdown" else bundle.to_dict()


@app.post("/ask/stream")
async def ask_stream(req: AskRequest) -> StreamingResponse:
    """Server-sent events: sweep_start, sweep_doc x45, sweep_done, tool_call, answer."""
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def on_progress(kind: str, data: dict) -> None:
        queue.put_nowait(f"event: {kind}\ndata: {json.dumps(data)}\n\n")

    async def run() -> None:
        try:
            bundle = await answer_question(
                store(), req.question, client=client(), synth_model=req.synth_model,
                triage_model=req.triage_model, max_turns=req.max_turns,
                run_sweep=req.run_sweep, on_progress=on_progress)
            payload = ({"markdown": bundle.to_markdown()} if req.format == "markdown"
                       else bundle.to_dict())
            await queue.put(f"event: answer\ndata: {json.dumps(payload)}\n\n")
        except Exception as exc:  # noqa: BLE001
            await queue.put("event: error\ndata: "
                            + json.dumps({"error": f"{type(exc).__name__}: {exc}"}) + "\n\n")
        finally:
            await queue.put(None)

    async def gen():
        task = asyncio.create_task(run())
        try:
            while (item := await queue.get()) is not None:
                yield item
        finally:
            task.cancel()

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --- erasure -------------------------------------------------------------
@app.post("/erase")
async def erase(req: EraseRequest) -> dict:
    async with LOCK:
        s = store()
        receipt = erase_person(s, req.name, mode=req.mode)
        s.save()
        return {"receipt": receipt.to_dict(), "verification": verify_erasure(s, req.name)}


@app.get("/erase/verify")
async def erase_verify(name: str) -> dict:
    return verify_erasure(store(), name)


@app.post("/rebuild")
async def rebuild() -> dict:
    """Rebuild from the corpus.

    This RESURRECTS anyone previously erased: no record of an erasure is kept
    anywhere, so it cannot be replayed and must be re-requested.
    """
    async with LOCK:
        build_index()
        STATE["store"] = s = Store.load()
    return {"stats": s.stats(), "erasures_replayed": None,
            "note": "erasures are not recorded and were NOT replayed; re-erase if needed"}


if __name__ == "__main__":
    raise SystemExit(main())
