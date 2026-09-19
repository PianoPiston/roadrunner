"""Corpus -> index. Parsing is where provenance is won or lost.

Three jobs, in this file's three sections:

1. **Transcripts.** Two dialects. Teams exports carry a header line per
   utterance ("Ana Duarte 2 minutes 35 seconds"); INTERNAL laptop recordings
   have only "Me:" and "Them:" and are deliberately left unattributed, because
   guessing which named human is "Me" would be fabrication. The hard part is
   that speech is split across utterances and interleaved with interruptions:

       Ana   2:35  "This is the session where we find out how bad the data"
       Priya 2:41  "Mm-hm."
       Ana   2:43  "is. Kwame,"

   Naive chunking shreds that sentence, so we stitch statements back together,
   joining only text that is actually present, and flag statements that are cut
   off and never resume.

2. **Email threads.** Stored newest-first with every earlier message quoted
   beneath. The trap is currency: the thread's top `Date:` header dates the most
   recent message only, so attaching it to the file makes every superseded
   figure look current. Each message therefore becomes its own dated unit.
   Headers appear in English, German and Swedish, with mixed 12/24-hour clocks;
   anything unparseable is recorded as None rather than guessed.

3. **Build.** Walk the corpus, parse, write data/index.json.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .core import CONFIG, Document, Registry, Unit, build_registry

# ══════════════════════════════════════════════════════════════════════════
# Transcripts
# ══════════════════════════════════════════════════════════════════════════

# "Ana Duarte 2 minutes 35 seconds" and its observed variants.
_HDR = re.compile(
    r"^(?P<name>.{2,60}?) "
    r"(?:(?P<m>\d+) minutes?(?: (?P<s>\d+) seconds?)?"
    r"|(?P<s2>\d+) seconds?)$"
)
# A new speaker block emits three preamble lines (bare name, doubled timestamp,
# initials) that carry no information and are dropped.
_TS_LINE = re.compile(r"^\d+:\d{2}(?::\d{2})?\d+:\d{2}(?::\d{2})?$")
_INITIALS = re.compile(r"^[A-ZÅÄÖØÆ]{2,3}$")
_META = re.compile(r"^(Meeting|Customer|Date|Phase|Attendees|Recording|Present):\s*(.*)$")

# Pure backchannel. Only used to decide whether a speaker interrupted their own
# sentence; never deleted, always kept as atoms.
_BACKCHANNEL = re.compile(
    r"^(mm+|mm-hm+|uh+|um+|hmm+|yeah|yep|yes|no|ok|okay|right|sure|exactly|"
    r"true|got it|i see|of course|indeed|sorry)[.,!?…]*$",
    re.I,
)
_TERMINAL = re.compile(r"[.!?…\"')\]]\s*$")
_TRAILS_OFF = re.compile(r"(\.\.\.|…)\s*$")

MAX_STITCH_GAP_SECONDS = 120
MAX_STITCH_INTERVENING = 8


@dataclass
class _Utt:
    """One raw utterance, before stitching."""
    idx: int
    speaker_raw: str
    t: int | None
    text: str
    line: int
    unit_id: str = ""
    meta: dict = field(default_factory=dict)


def _fmt_ts(t: int | None) -> str:
    return "" if t is None else f"{t // 60}:{t % 60:02d}"


def _is_backchannel(text: str) -> bool:
    return bool(_BACKCHANNEL.match(text.strip())) and len(text.split()) <= 3


def _is_open(text: str) -> bool:
    """True when the utterance stops mid-sentence."""
    t = text.strip()
    if not t:
        return False
    return bool(_TRAILS_OFF.search(t)) or not _TERMINAL.search(t)


def parse_transcript(path: Path, short: str, registry: Registry) -> tuple[Document, list[Unit]]:
    raw = path.read_text(encoding="utf-8")
    lines = raw.split("\n")

    meta: dict[str, str] = {}
    for ln in lines[:30]:
        m = _META.match(ln.strip())
        if m:
            meta[m.group(1).lower()] = m.group(2).strip()

    doc = Document(
        doc_id=f"{path.parent.name}/{path.stem}",
        kind="transcript",
        path=str(path),
        title=meta.get("meeting", path.stem),
        date=meta.get("date"),
        phase=meta.get("phase"),
        participants=[a.strip() for a in re.split(r"[;,]", meta.get("attendees", "")) if a.strip()],
        internal="INTERNAL" in path.stem,
        meta={"short": short, "dialect": "internal" if "Me:" in raw else "teams"},
    )

    utts = (_parse_internal(lines) if doc.meta["dialect"] == "internal"
            else _parse_teams(lines, registry))
    units = _stitch(utts, doc, registry)
    doc.n_units = len(units)
    return doc, units


def _parse_teams(lines: list[str], registry: Registry) -> list[_Utt]:
    """Split on canonical header lines; drop the next block's preamble."""
    heads: list[tuple[int, str, int]] = []  # (line_no, speaker, seconds)
    for i, ln in enumerate(lines):
        m = _HDR.match(ln.strip())
        if not m:
            continue
        name = m.group("name").strip()
        # Guard against body text that happens to end in a duration.
        if not registry.resolve(name) and name != "Unknown Speaker":
            continue
        secs = (int(m.group("m") or 0) * 60 + int(m.group("s") or 0)) if m.group("m") \
            else int(m.group("s2") or 0)
        heads.append((i, name, secs))

    utts: list[_Utt] = []
    for n, (line_no, name, secs) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
        body = lines[line_no + 1:end]
        while body:
            tail = body[-1].strip()
            if not tail or _TS_LINE.match(tail) or _INITIALS.match(tail) or tail == "Unknown Speaker":
                body.pop()
            elif registry.resolve(tail) and len(tail.split()) <= 4:
                body.pop()
            else:
                break
        text = " ".join(x.strip() for x in body if x.strip()).strip()
        if text:
            utts.append(_Utt(idx=len(utts), speaker_raw=name, t=secs, text=text, line=line_no + 1))
    return utts


def _parse_internal(lines: list[str]) -> list[_Utt]:
    """Me:/Them: recordings. Speaker identity is genuinely unknown."""
    utts: list[_Utt] = []
    for i, ln in enumerate(lines):
        m = re.match(r"^(Me|Them):\s*(.*)$", ln.strip())
        if m and m.group(2).strip():
            utts.append(_Utt(idx=len(utts), speaker_raw=m.group(1), t=None,
                             text=m.group(2).strip(), line=i + 1,
                             meta={"unattributed": True}))
    return utts


def _stitch(utts: list[_Utt], doc: Document, registry: Registry) -> list[Unit]:
    """Join sentences split across utterances. Never invents text."""
    for u in utts:
        u.unit_id = f"{doc.meta['short']}.u{u.idx:04d}"

    consumed: set[int] = set()
    units: list[Unit] = []

    for u in utts:
        if u.idx in consumed:
            continue
        members, interruptions, cur = [u], [], u
        while _is_open(cur.text):
            nxt, intervening = None, []
            for cand in utts[cur.idx + 1:]:
                if cand.idx - cur.idx > MAX_STITCH_INTERVENING:
                    break
                if cur.t is not None and cand.t is not None and cand.t - cur.t > MAX_STITCH_GAP_SECONDS:
                    break
                if cand.speaker_raw != u.speaker_raw:
                    intervening.append(cand)
                elif _is_backchannel(cand.text):
                    # The speaker filling their own pause is an aside, not the
                    # continuation of the sentence.
                    intervening.append(cand)
                else:
                    nxt = cand
                    break
            if nxt is None:
                break
            for iv in intervening:
                consumed.add(iv.idx)
                interruptions.append(f"{iv.speaker_raw} at {_fmt_ts(iv.t)}: {iv.text}"
                                     if iv.t is not None else f"{iv.speaker_raw}: {iv.text}")
            members.append(nxt)
            consumed.add(nxt.idx)
            cur = nxt

        consumed.add(u.idx)
        units.append(_make_unit(members, interruptions, doc, registry, len(units)))

    return units


def _make_unit(members: list[_Utt], interruptions: list[str], doc: Document,
               registry: Registry, seq: int) -> Unit:
    first, last = members[0], members[-1]
    text = re.sub(r"\s+", " ", " ".join(m.text.strip() for m in members)).strip()

    person = registry.resolve(first.speaker_raw)
    unattributed = first.meta.get("unattributed", False)

    if first.t is not None:
        locator = (f"at {_fmt_ts(first.t)}" if first is last
                   else f"{_fmt_ts(first.t)}–{_fmt_ts(last.t)}")
    else:
        locator = f"line {first.line}" if first is last else f"lines {first.line}–{last.line}"

    return Unit(
        unit_id=f"{doc.meta['short']}.s{seq:04d}",
        doc_id=doc.doc_id,
        doc_kind="transcript",
        seq=seq,
        text=text,
        date=doc.date,
        speaker=None if unattributed or not person else person.pid,
        speaker_display=(first.speaker_raw if unattributed or not person else person.display),
        speaker_org=None if unattributed or not person else person.org,
        locator=locator,
        truncated=_is_open(text),
        interrupted_by=interruptions,
        spans_units=[m.unit_id for m in members],
        meta={
            "t_start": first.t,
            "t_end": last.t,
            "meeting": doc.title,
            "phase": doc.phase,
            "internal": doc.internal,
            "unattributed_dialect": unattributed,
            "trails_off": bool(_TRAILS_OFF.search(text)),
        },
    )


# ══════════════════════════════════════════════════════════════════════════
# Email threads
# ══════════════════════════════════════════════════════════════════════════

_H = {
    "from": ("From", "Von", "Från"),
    "sent": ("Sent", "Gesendet", "Skickat", "Date"),
    "to": ("To", "An", "Till"),
    "cc": ("Cc", "Kopia", "CC"),
    "subject": ("Subject", "Betreff", "Ämne"),
}
_KEY_OF = {v.lower(): k for k, vs in _H.items() for v in vs}
_HEADER_RE = re.compile(
    r"^(" + "|".join(sorted({v for vs in _H.values() for v in vs}, key=len, reverse=True))
    + r"):\s*(.*)$"
)
# A new message starts at one of these. `Date:` only starts the top message.
_BOUNDARY_RE = re.compile(r"^(Sent|Gesendet|Skickat|Date):\s*(.+)$")

_MONTHS = {
    m.lower(): i
    for names in (
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"],
        ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
         "August", "September", "Oktober", "November", "Dezember"],
        ["januari", "februari", "mars", "april", "maj", "juni", "juli",
         "augusti", "september", "oktober", "november", "december"],
    )
    for i, m in enumerate(names, 1)
}

_DATE_EN = re.compile(r"[A-Za-zÄÖÅäöå]+,\s*([A-Za-zÄÖÅäöå]+)\s+(\d{1,2}),\s*(\d{4})\s+(\d{1,2}):(\d{2})\s*(AM|PM)?", re.I)
_DATE_DE = re.compile(r"[A-Za-zÄÖÜäöüß]+,\s*(\d{1,2})\.\s*([A-Za-zÄÖÜäöüß]+)\s+(\d{4})\s+(\d{1,2}):(\d{2})")
_DATE_SV = re.compile(r"den\s+(\d{1,2})\s+([A-Za-zÄÖÅäöå]+)\s+(\d{4})\s+(\d{1,2}):(\d{2})", re.I)

# Every observed form of a stripped attachment. Never match on just one.
_IMAGE_RE = re.compile(
    r"\[Image removed by sender\]|\[cid:[^\]]*\]|Bild borttagen av avsändaren|^Image$",
    re.I | re.M,
)
_BANNER_RE = re.compile(
    r"^This email originated from outside of RELEX\..*?report button\.\s*$", re.I | re.M)
_THREAD_META_RE = re.compile(r"^\s*(Messages in thread:\s*\d+|\*\*\*.*)$", re.M)
_BOILERPLATE_RE = re.compile(
    r"^\s*(If there is anything else you'd like to see in these update emails.*|"
    r"Hereby the weekly update\.|Plan better\. Sell more\. Waste less.*)$", re.I | re.M)

_SIG_START = re.compile(
    r"^\s*(Kind regards|Best regards|Mit freundlichen Grüßen|Med vänliga hälsningar|"
    r"Venliga hälsningar|Regards|Thanks|Thank you|BR|Br|Best|Cheers|Hälsningar|"
    r"Viele Grüße|Beste Grüße)[,.!]?\s*$", re.I)

# Lines that belong to a signature block: contact details, company lines, and
# job titles. Shared by both signature tests below.
_ROLES = (r"Head of|Chief|Project Manager|Account (?:Executive|Director)|"
          r"Solution (?:Consultant|Architect)|Technical Consultant|Service Delivery|"
          r"IT Integration Lead|Category Manager|Data Protection Officer|"
          r"Principal Consultant|Consultant")
_CONTACT = (r"\+\d[\d\s\-()]{6,}"                                     # phone
            r"|[\w.\-]+@[\w.\-]+"                                     # email
            r"|.*\b(?:GmbH|AB|Oy|Ltd|BV)\b.*"                         # legal entity
            r"|.*(?:relexsolutions|acme-org|meridian-consulting)\.example.*"
            r"|Connect with me|LinkedIn\w*"
            r"|(?:" + _ROLES + r")\b.*")
# Trailing junk left above a salutation, incl. a street address with a postcode.
_SIG_NOISE = re.compile(
    r"^(?:" + _CONTACT + r"|Plan better\..*|Image|\[image\]|UTC [+\-].*|"
    r".*\|\s*UTC.*|[A-ZÅÄÖ][\w\s.\-]*\d{3,}[\w\s.\-]*)$", re.I)
# Lines that mark a signature block when they follow a bare name.
_SIG_FOLLOWER = re.compile(
    r"^(?:" + _CONTACT + r"|.*\b\d{3}\s?\d{2}\b.*|.*\|.*UTC.*)$", re.I)


@dataclass
class _Msg:
    headers: dict[str, str]
    body_lines: list[str]


def _parse_date(s: str) -> datetime | None:
    """English, German or Swedish header date. None when unparseable."""
    m = _DATE_EN.search(s.strip())
    if m and _MONTHS.get(m.group(1).lower()):
        h, ap = int(m.group(4)), (m.group(6) or "").upper()
        if ap == "PM" and h != 12:
            h += 12
        elif ap == "AM" and h == 12:
            h = 0
        return datetime(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)),
                        h, int(m.group(5)))
    for rx in (_DATE_DE, _DATE_SV):           # both day-month-year
        m = rx.search(s.strip())
        if m and _MONTHS.get(m.group(2).lower()):
            return datetime(int(m.group(3)), _MONTHS[m.group(2).lower()],
                            int(m.group(1)), int(m.group(4)), int(m.group(5)))
    return None


def clean_body(lines: list[str], registry: Registry | None = None) -> tuple[str, int]:
    """Strip banner, signature and attachment placeholders.

    Returns the cleaned body and the number of stripped attachments, because
    "the chart is attached" is evidence that the archive does NOT contain the
    chart -- which matters when a question asks for a figure.
    """
    text = "\n".join(lines)
    n_images = len(_IMAGE_RE.findall(text))
    for rx in (_BANNER_RE, _IMAGE_RE, _THREAD_META_RE):
        text = rx.sub("", text)

    out: list[str] = []
    for ln in text.split("\n"):
        if _SIG_START.match(ln):
            break
        out.append(ln)

    def _is_trailing_noise(ln: str) -> bool:
        t = ln.strip()
        if not t or _SIG_NOISE.match(t):
            return True
        return bool(registry and len(t.split()) <= 4 and registry.resolve(t))

    while out and _is_trailing_noise(out[-1]):
        out.pop()

    # A signature often has no salutation above it: a bare name followed by
    # role, phone, address. Scan forward so we cut at the FIRST line of the
    # block (the name), not at some later line that also looks like signature.
    if registry:
        for i in range(max(0, len(out) - 14), len(out)):
            t = out[i].strip()
            if not t or len(t.split()) > 4 or not registry.resolve(t):
                continue
            rest = [x.strip() for x in out[i + 1:] if x.strip()]
            if not rest or len(rest) > 10:
                continue
            if sum(1 for w in rest if _SIG_FOLLOWER.match(w)) >= max(1, int(len(rest) * 0.6)):
                out = out[:i]
                break
        while out and _is_trailing_noise(out[-1]):
            out.pop()
    while out and not out[0].strip():
        out.pop(0)

    body = _BOILERPLATE_RE.sub("", "\n".join(out).strip())
    return re.sub(r"\n{3,}", "\n\n", body).strip(), n_images


def parse_email_thread(path: Path, short: str, registry: Registry,
                       kind: str = "email") -> tuple[Document, list[Unit]]:
    raw = path.read_text(encoding="utf-8")
    doc_id = f"{path.parent.name}/{path.stem}"
    declared = re.search(r"^Messages in thread:\s*(\d+)", raw, re.M)

    msgs = _split_messages(raw.split("\n"))
    total = len(msgs)
    units: list[Unit] = []

    # Threads are stored newest-first. Number messages as Outlook shows them
    # (1 = oldest) and date each from its own header.
    for i, msg in enumerate(msgs):
        body, n_images = clean_body(msg.body_lines, registry)
        if not body:
            continue
        sent = _parse_date(msg.headers.get("sent", ""))
        sender_raw = msg.headers.get("from", "")
        sender = registry.resolve(sender_raw)

        recips = []
        for r in _split_people(msg.headers.get("to", "")) + _split_people(msg.headers.get("cc", "")):
            p = registry.resolve(r)
            recips.append(p.pid if p else r)

        position = total - i
        units.append(Unit(
            unit_id=f"{short}.m{position:02d}",
            doc_id=doc_id,
            doc_kind=kind,  # type: ignore[arg-type]
            seq=len(units),
            text=body,
            date=sent.isoformat(timespec="minutes") if sent else None,
            speaker=sender.pid if sender else None,
            speaker_display=sender.display if sender else (sender_raw or None),
            speaker_org=sender.org if sender else None,
            recipients=recips,
            locator=f"message {position} of {total}"
                    + (f", {sent.date().isoformat()}" if sent else ", date unparsed"),
            meta={
                "subject": msg.headers.get("subject"),
                "from_raw": sender_raw,
                "attachments_stripped": n_images,
                "thread_position": position,
                "thread_total": total,
                "header_language": msg.headers.get("_lang", "en"),
            },
        ))

    subject = units[0].meta.get("subject") if units else None
    doc = Document(
        doc_id=doc_id,
        kind=kind,  # type: ignore[arg-type]
        path=str(path),
        title=subject or path.stem,
        date=max((u.date for u in units if u.date), default=None),
        subject=subject,
        participants=sorted({u.speaker_display for u in units if u.speaker_display}),
        n_units=len(units),
        meta={
            "short": short,
            "declared_messages": int(declared.group(1)) if declared else None,
            "parsed_messages": total,
            "first_date": min((u.date for u in units if u.date), default=None),
        },
    )
    return doc, units


def _split_people(s: str) -> list[str]:
    return [p.strip() for p in re.split(r"[;,](?![^<]*>)", s or "") if p.strip()]


def _split_messages(lines: list[str]) -> list[_Msg]:
    """Boundaries are Sent/Gesendet/Skickat lines, plus the top Date: line."""
    bounds = [i for i, ln in enumerate(lines) if _BOUNDARY_RE.match(ln.strip())]
    msgs: list[_Msg] = []

    for n, b in enumerate(bounds):
        # Headers cluster around the boundary: walk out in both directions.
        start = b
        while start > 0 and _HEADER_RE.match(lines[start - 1].strip()):
            start -= 1
        end_headers = b + 1
        while end_headers < len(lines) and _HEADER_RE.match(lines[end_headers].strip()):
            end_headers += 1

        headers: dict[str, str] = {"_lang": "en"}
        for i in range(start, end_headers):
            hm = _HEADER_RE.match(lines[i].strip())
            if not hm:
                continue
            key = _KEY_OF.get(hm.group(1).lower())
            if key and key not in headers:
                headers[key] = hm.group(2).strip()
            if hm.group(1) in ("Von", "Gesendet", "An", "Betreff"):
                headers["_lang"] = "de"
            elif hm.group(1) in ("Från", "Skickat", "Till", "Ämne", "Kopia"):
                headers["_lang"] = "sv"

        body_end = len(lines)
        if n + 1 < len(bounds):
            body_end = bounds[n + 1]
            while body_end > end_headers and _HEADER_RE.match(lines[body_end - 1].strip()):
                body_end -= 1
        msgs.append(_Msg(headers=headers, body_lines=lines[end_headers:body_end]))
    return msgs


# ══════════════════════════════════════════════════════════════════════════
# Build
# ══════════════════════════════════════════════════════════════════════════

def _short(path: Path) -> str:
    """Stable per-document prefix for unit ids: T06, E07, R01."""
    prefix = {"transcripts": "T", "emails": "E", "reports": "R"}[path.parent.name]
    return f"{prefix}{path.stem.split('_')[0]}"


def fingerprint(corpus_dir: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(corpus_dir.glob("*/*.txt")):
        h.update(p.name.encode())
        h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()[:16]


def build_index(corpus_dir: Path | None = None, out_path: Path | None = None) -> dict:
    corpus_dir = corpus_dir or CONFIG.corpus_dir
    out_path = out_path or CONFIG.index_path
    if not corpus_dir.exists():
        raise FileNotFoundError(f"corpus not found: {corpus_dir}")

    files = sorted(corpus_dir.glob("*/*.txt"))
    # People are discovered from the whole corpus before any file is parsed, so
    # an off-roster name is already resolvable when it is first encountered.
    registry = build_registry("".join(p.read_text(encoding="utf-8") for p in files))

    documents: list[Document] = []
    units: list[Unit] = []
    for path in files:
        if path.parent.name == "transcripts":
            doc, us = parse_transcript(path, _short(path), registry)
        else:
            kind = "report" if path.parent.name == "reports" else "email"
            doc, us = parse_email_thread(path, _short(path), registry, kind)
        documents.append(doc)
        units.extend(us)

    index = {
        "schema_version": 1,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "corpus_dir": str(corpus_dir),
        "corpus_fingerprint": fingerprint(corpus_dir),
        "people": {pid: p.to_dict() for pid, p in registry.people.items()},
        "documents": [d.to_dict() for d in documents],
        "units": [u.to_dict() for u in units],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    return index
