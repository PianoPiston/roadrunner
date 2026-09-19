"""Erasure is scored on completeness and honesty, so both are tested."""
import json


def test_erasure_removes_every_alias_from_the_live_index(store):
    from acme_agent.deletion import erase_person, verify_erasure
    erase_person(store, "Kwame Boateng")
    check = verify_erasure(store, "Kwame Boateng")
    assert check["clean"], check["surviving_text_hits"][:5]
    assert check["surviving_person_records"] == []


def test_erasure_catches_first_name_and_email_forms(store):
    from acme_agent.deletion import erase_person
    from acme_agent.retrieval import grep
    erase_person(store, "Kwame Boateng")
    for surface in ("Kwame", "Boateng", "k.boateng"):
        assert not grep(store, surface), f"{surface} survived"


def test_erasure_removes_authorship_and_leaves_an_auditable_tombstone(store):
    from acme_agent.deletion import TOMBSTONE, erase_person
    r = erase_person(store, "Kwame Boateng")
    assert r.units_authored_removed > 0
    u = store.unit(r.unit_ids_authored[0])
    assert u.redacted and u.speaker is None and u.text == TOMBSTONE
    # A citation to an erased unit must resolve to "withheld", not "not found".
    assert store.unit(r.unit_ids_authored[0]) is not None


def test_erased_units_cannot_be_cited(store):
    from acme_agent.deletion import erase_person
    from acme_agent.answer import Citation, verify_citation
    r = erase_person(store, "Kwame Boateng")
    v = verify_citation(store, Citation(unit_id=r.unit_ids_authored[0], quote="anything"))
    assert not v.ok and "erasure" in v.problem


def test_receipt_separates_what_survived_from_what_did_not(store):
    from acme_agent.deletion import erase_person
    r = erase_person(store, "Kwame Boateng")
    assert r.survived and r.did_not_survive
    assert all("restated" in s["why"] for s in r.survived)
    assert all("only ever stated" in s["why"] for s in r.did_not_survive)


def test_nothing_about_an_erased_person_is_written_anywhere(store, tmp_path):
    """The point of an erasure is that no trace is kept -- including a record OF
    the erasure. "We deleted Kwame Boateng" still contains Kwame Boateng."""
    import json
    from acme_agent.deletion import erase_person
    erase_person(store, "Kwame Boateng")
    store.save()

    written = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert "deletions" not in written, "the index must not record who was erased"

    # Compute the booleans first: asserting `x not in blob` directly makes pytest
    # render the whole 4MB index into the failure message.
    blob = json.dumps(written, ensure_ascii=False)
    survivors = [s for s in ("Kwame", "Boateng", "k.boateng") if s in blob]
    assert not survivors, f"these surfaced in the saved index: {survivors}"
    assert not list(tmp_path.glob("*ledger*")), "no audit ledger may be written"


def test_a_rebuild_resurrects_an_erased_person(store, corpus_dir, tmp_path):
    """The documented consequence of keeping no record: rebuilding from the
    corpus brings them back, and the erasure must be re-requested."""
    from acme_agent.core import Store
    from acme_agent.deletion import erase_person, verify_erasure
    from acme_agent.ingest import build_index
    erase_person(store, "Kwame Boateng")
    assert verify_erasure(store, "Kwame Boateng")["clean"]

    build_index(corpus_dir, tmp_path / "index.json")
    fresh = Store.load(tmp_path / "index.json")
    assert not verify_erasure(fresh, "Kwame Boateng")["clean"], "rebuild resurrects"


def test_offroster_person_can_be_erased(store):
    """Someone who appears once, in a data sample, must be erasable too."""
    from acme_agent.deletion import erase_person, verify_erasure
    from acme_agent.retrieval import grep
    assert grep(store, "Marika Lindqvist")
    erase_person(store, "Marika Lindqvist")
    assert verify_erasure(store, "Marika Lindqvist")["clean"]


def test_two_letter_initials_are_not_redacted_from_free_text(store):
    """'KB' identifies a speaker but also means kilobytes. Redacting it in prose
    would damage unrelated units."""
    from acme_agent.deletion import _text_aliases
    assert "KB" not in _text_aliases(["Kwame Boateng", "Kwame", "KB"])
