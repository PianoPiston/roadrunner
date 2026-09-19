"""Parsing is where provenance is won or lost, so it is tested against the
declared ground truth in the corpus itself."""
import re

import pytest


def test_every_thread_parses_exactly_the_declared_number_of_messages(corpus_dir, registry):
    from acme_agent.ingest import parse_email_thread
    for path in sorted(corpus_dir.glob("emails/*.txt")) + sorted(corpus_dir.glob("reports/*.txt")):
        declared = int(re.search(r"^Messages in thread:\s*(\d+)", path.read_text(encoding="utf-8"), re.M).group(1))
        kind = "report" if path.parent.name == "reports" else "email"
        short = ("R" if kind == "report" else "E") + path.stem.split("_")[0]
        doc, units = parse_email_thread(path, short, registry, kind)
        assert doc.meta["parsed_messages"] == declared, f"{path.name}: {doc.meta['parsed_messages']} != {declared}"
        assert len(units) == declared


def test_every_message_gets_its_own_date_not_the_threads(store):
    """The currency trap: a reverse-chronological thread must not stamp the
    newest date on older messages."""
    thread = store.doc_units("emails/07_op-id-field-exclusion")
    dates = [u.date for u in thread]
    assert all(dates), "every message must be dated"
    assert len(set(d[:10] for d in dates)) > 1, "messages must not share one date"
    assert dates == sorted(dates, reverse=True), "stored newest-first"


@pytest.mark.parametrize("sample,expected", [
    ("Monday, November 24, 2025 17:55", "2025-11-24T17:55"),
    ("Wednesday, November 19, 2025 11:44 AM", "2025-11-19T11:44"),
    ("Tuesday, February 24, 2026 2:15 PM", "2026-02-24T14:15"),
    ("Montag, 29. Juni 2026 10:15", "2026-06-29T10:15"),
    ("Freitag, 12. Dezember 2025 17:10", "2025-12-12T17:10"),
    ("den 26 februari 2026 16:20", "2026-02-26T16:20"),
    ("den 20 augusti 2024 09:05", "2024-08-20T09:05"),
])
def test_dates_parse_in_all_three_header_languages(sample, expected):
    from acme_agent.ingest import _parse_date
    got = _parse_date(sample)
    assert got is not None and got.isoformat(timespec="minutes") == expected


def test_all_135_messages_are_dated(store):
    msgs = [u for u in store.units if u.doc_kind in ("email", "report")]
    assert len(msgs) == 135
    assert all(u.date for u in msgs)


def test_interrupted_sentence_is_stitched_back_together(store):
    """Ana's sentence is split over three utterances by two interruptions.
    Naive chunking separates 'how bad the data' from 'is'."""
    u = store.unit("T06.s0000")
    assert "how bad the data is" in u.text
    assert len(u.spans_units) >= 3
    assert any("Mm-hm" in i for i in u.interrupted_by)


def test_cut_off_statements_are_flagged_and_not_completed(store):
    u = store.unit("T06.s0018")
    assert u.truncated is True
    assert u.text.rstrip().endswith("...")
    # The figure that was about to be given is not in the unit.
    assert not any(ch.isdigit() for ch in u.text.split("roughly")[-1])


def test_internal_recordings_are_not_falsely_attributed(store):
    units = store.doc_units("transcripts/09_2025-02-12_INTERNAL-account-review")
    assert units, "internal transcript must parse"
    assert all(u.speaker is None for u in units), "Me/Them must not be resolved to a person"
    assert all(u.speaker_display in ("Me", "Them") for u in units)
    assert store.doc("transcripts/09_2025-02-12_INTERNAL-account-review").internal


def test_signatures_and_image_placeholders_are_stripped(store):
    msgs = [u for u in store.units if u.doc_kind in ("email", "report")]
    for placeholder in ("[Image removed by sender]", "[cid:image001.png]",
                        "Bild borttagen av avsändaren"):
        assert not any(placeholder in u.text for u in msgs)
    leaked = [u.unit_id for u in msgs if re.search(r"relexsolutions\.example|Vasagatan|Hansaring", u.text)]
    assert len(leaked) <= 1, f"signature blocks leaked into {leaked}"


def test_attachments_are_recorded_as_missing_evidence(store):
    """A stripped image is evidence the archive lacks a chart, which matters
    when a question asks for a figure."""
    withattach = [u for u in store.units if u.meta.get("attachments_stripped")]
    assert withattach


def test_unit_ids_are_stable_across_rebuilds(corpus_dir, tmp_path):
    from acme_agent.ingest import build_index
    a = build_index(corpus_dir, tmp_path / "a.json")
    b = build_index(corpus_dir, tmp_path / "b.json")
    assert [u["unit_id"] for u in a["units"]] == [u["unit_id"] for u in b["units"]]
    assert a["corpus_fingerprint"] == b["corpus_fingerprint"]
