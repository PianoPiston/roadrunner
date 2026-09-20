# Acme archive agent

Backend for the RELEX challenge track, AaltoAI Hackathon 2026.

Two-stage, citation-grounded question answering over a 45-document corporate
archive: a cheap model reads **everything**, an expensive model decides what is
true and cites it, and Python — not the model — checks that every citation is
real.

```
question
   │
   ├─ 1. SWEEP      gpt-5.4-mini reads all 45 documents concurrently
   │                 (~70k tokens, document-first so the prefix stays cached)
   │                 → relevance, kept unit ids, verbatim quotes, flags
   │
   ├─ 2. ANALYST    gpt-5.6-terra via the OpenAI Agents SDK, given the digest plus
   │                 verbatim evidence, with 11 function tools for exact search,
   │                 figures, timelines, document windows, quote checking, erasure
   │                 → structured Answer: claims, citations, gaps, abstentions
   │
   └─ 3. VERIFY     deterministic. Every quote must be a real substring of the
                    cited unit; every citation's document, date, speaker and
                    position is rendered from the index, never from the model
```

## Quickstart

Needs Python 3.11+, [Poetry](https://python-poetry.org/docs/#installation),
Node 18+, and an OpenAI API key.

```bash
git clone <this repo> && cd acme-agent
./setup.sh                       # deps, .env, and builds the index
```

Put your key in `.env` (`OPENAI_API_KEY=sk-...`), then:

```bash
npm --prefix acme-chat run start
```

That starts both halves — FastAPI on **:8000** and the web app on **:5173** —
and prints a link. Open <http://localhost:5173> and pick a view.

The archive itself must sit at `corpus/acme/` (containing `transcripts/`,
`emails/` and `reports/`). `setup.sh` tells you if it is missing.

**No API key?** Everything except asking a question still works: all three views
load, search, figures, the citation checker and erasure make no model calls.

## Why read everything instead of embedding search

The archive is ~58,000 words — about 70k tokens once parsed. Reading all of it
with a cheap model costs a fraction of a cent per question, and it is the only
approach that answers the questions this challenge actually scores:

- *"What was agreed and then never done?"* — absence has no embedding. You can
  only find it by covering the whole timeline and observing a gap.
- *"Which of these figures is current?"* — requires seeing **all** the values,
  not the top-k most similar ones. Top-k retrieval returns the best-matching
  value, which is frequently the superseded one.
- *"Is that true?"* — requires reading the thing the report is evidence *for*.

There is also no vector index to be wrong about during erasure. See below.

## The corpus, as it actually is

Parsing decisions were made against the bytes, not the README. What matters:

| Reality | Consequence |
|---|---|
| 135 email messages across 22 threads, stored newest-first | Each message is its own dated unit. The thread's top `Date:` is **not** every message's date — attaching it would make every superseded figure look current. |
| Headers in English, German (`Gesendet:`) and Swedish (`Skickat:`), mixed 12/24-hour clocks | All three parsed; 135/135 messages dated, verified against each thread's declared count. |
| Teams transcripts split sentences across utterances, interleaved with interruptions | A statement-stitching pass rejoins them. `"...how bad the data"` + *(Priya: "Mm-hm.")* + `"is. Kwame,"` becomes one citable statement with the interruptions recorded. Naive chunking shreds this. |
| 21 statements are cut off mid-sentence and never resume | Flagged `truncated` at ingest. The flag is rendered into every prompt as *"do NOT complete it"*, and the verifier warns if a claim rests on one. One of them is a figure being cut off mid-sentence in the September 2024 master-data workshop. |
| Three transcripts are internal RELEX recordings labelled only `Me:` / `Them:` | Deliberately left unattributed. Guessing which named human is "Me" is fabrication. Documents are flagged `internal`, and the verifier warns when one is cited as customer agreement. |
| The roster is larger than the README's 15 people | People are **discovered** from the corpus, not hardcoded: staff who appear only as email addresses, and operator names inside a data sample. |
| Four different image placeholders, incl. `Bild borttagen av avsändaren` | All stripped, but the **count** is retained: "chart attached" is evidence the archive does *not* contain the chart. |

Everything above is asserted by the test suite against the corpus itself.

## Install

Python version is pinned by `.python-version` (pyenv); dependencies and the
virtualenv are managed by Poetry. `poetry.toml` keeps the venv in-project at
`.venv/`, so it is disposable and gitignored.

```bash
pyenv install --skip-existing "$(cat .python-version)"
poetry env use "$(pyenv which python)"
poetry install
cp .env.example .env     # then put your OPENAI_API_KEY in it
```

Without pyenv, `poetry install` alone works against any Python matching
`requires-python` (>=3.11).

Put the archive at `corpus/acme/` inside the repo (it should contain
`transcripts/`, `emails/` and `reports/`), or point `ACME_CORPUS_DIR` in `.env`
somewhere else. Relative paths resolve against the repo root.

## Use

```bash
poetry run acme-agent build                      # parse → data/index.json
poetry run acme-agent stats
poetry run acme-agent ask "What proportion of articles had shelf-life data populated?"
poetry run acme-agent practice --out-dir answers # all 8 answerable practice questions
poetry run acme-agent serve --port 8000
```

Inside `poetry shell` the `acme-agent` prefix is enough.

Two commands make no model calls at all and are instant — useful while
debugging, and useful in a demo:

```bash
poetry run acme-agent grep "OP_ID"
poetry run acme-agent figures "shelf life"
```

### HTTP

| Route | Purpose |
|---|---|
| `POST /ask` | `{"question": "...", "format": "json"\|"markdown"}` |
| `POST /ask/stream` | Same, as SSE: `sweep_start`, `sweep_doc` ×45, `sweep_done`, `tool_call`, `verified`, `answer` |
| `POST /erase` | `{"name": "Kwame Boateng"}` → receipt **and** an independent verification scan |
| `GET /erase/verify?name=` | Re-scan the live index for surviving traces |
| `POST /rebuild` | Rebuild from the corpus. **Resurrects** anyone erased |
| `POST /verify` | `{"unit_id","quote"}` → is this citation real? |
| `GET /grep?pattern=&regex=` | Exact/regex search. No model calls |
| `GET /figures?topic=` | Every dated numeric claim. No model calls |
| `GET /documents`, `/documents/{id}`, `/units/{id}`, `/people`, `/stats` | Index access |

`GET /units/{id}` on an erased unit returns **410 Gone**, not 404 — "withheld"
and "never existed" are different facts.

## Citations

A citation is a `unit_id` plus a verbatim quote. Unit ids are stable across
rebuilds (derived from document and ordinal position, never content hashing), so
a citation stays valid.

- Transcript: `transcripts/06_… — at 4:39 — Kwame Boateng (RELEX) — 2024-09-24`
- Email: `emails/07_… — message 3 of 4, 2025-11-24 — Kwame Boateng (RELEX)`

The model supplies only the id and the quote. Everything a grader reads —
document, position, speaker, organisation, date — is looked up in the index
afterwards. A model that misremembers a date cannot introduce that error into a
citation, and a quote that is not in the unit is reported as a fabrication
rather than printed.

## Erasure

`erase_person()` addresses the three ways this goes wrong:

1. **Under-deletion by surface form.** The archive says "Kwame Boateng",
   "Kwame", "Boateng" and "k.boateng@relexsolutions.example". All aliases are
   erased, longest-first, diacritic-folded. Two-letter initials are used to
   match a *speaker* but never redacted from prose, because `KB` also means
   kilobytes.
2. **No record of the erasure.** Nothing identifying the subject is written
   anywhere — no name, no aliases, no audit ledger. Keeping "we deleted Kwame
   Boateng" is still keeping Kwame Boateng. The consequence is deliberate and
   tested: `acme-agent build` resurrects them from the corpus, so a rebuild must
   be followed by a fresh erasure request.
3. **Dishonest reporting.** Deleting a person deletes their **attribution**, not
   necessarily the facts they reported. The receipt computes this: a figure
   restated elsewhere by someone else survives; a figure only ever given by the
   erased subject does not. Both lists are in the receipt, with reasons.

Erased units become tombstones rather than holes, so a dangling citation
resolves to *withheld* rather than *not found*. `who_is` on an erased person is
deliberately indistinguishable from one who never existed — confirming that a
particular name *was* erased would leak the name.

There are **no embeddings to purge**, by design — which is a stronger answer to
"erase it from your embeddings" than purging some and hoping.

## Layout

Seven files, in dependency order — each one reads top to bottom, and nothing
below imports anything above it out of order.

```
src/acme_agent/
  core.py        Config; Person/Unit/Document; the person registry;
                 Store (the loaded index, lookup, redaction awareness)
  ingest.py      corpus → data/index.json: transcript dialects and statement
                 stitching, email threads in 3 header languages with
                 per-message dating and signature stripping
  retrieval.py   no model calls at all: BM25, exact/regex grep, dated figure
                 extraction, and unit/document rendering with inline provenance
  answer.py      the answer contract (Answer / Claim / Citation / Gap /
                 Abstention) and the deterministic citation verifier
  agent.py       the pipeline: stage 1 sweep over all 45 documents, the 10
                 function tools, stage 2 analyst, orchestration
  deletion.py    erasure, impact analysis, independent verification scan
  app.py         transports: CLI and FastAPI server

acme-chat/                     React frontend (Vite), three role views
  src/pages/Home.jsx           landing page: pick Developer / Manager / Marketing
  src/pages/DevView.jsx        grep, unit inspector, citation checker, index health
  src/pages/ManagerView.jsx    timeline, silences, participation, erasure
  src/pages/MarketingView.jsx  story arc, dated figures, publish clearance
  src/components/ViewShell.jsx shared chrome + the chatbox every view uses
  src/lib/usage.js             the per-view token counter
```

~1,970 lines of code plus ~430 of docstrings and model prompts.

## Tests

```bash
poetry run pytest -q
```

46 tests, no API key required. They assert against the corpus itself: declared
message counts, all three date languages, sentence stitching, cut-off detection,
alias resolution, citation verification, and that an erasure survives a rebuild.

They need the archive, so they read `ACME_CORPUS_DIR` from `.env` and **skip**
with a message if it does not resolve. Each test builds its own index in a temp
directory, so a test run never touches `data/`.

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `ACME_TRIAGE_MODEL` | `gpt-5.4-mini` | Called 45× per question |
| `ACME_SYNTH_MODEL` | `gpt-5.6-terra` | Called once, with tools |
| `ACME_TRIAGE_CONCURRENCY` | `12` | Fan-out width |
| `ACME_TRIAGE_KEEP_THRESHOLD` | `2` | Minimum relevance passed to stage 2 |
| `ACME_MAX_EVIDENCE_UNITS` | `160` | Cap on evidence handed to stage 2 |
