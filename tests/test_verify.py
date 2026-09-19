from acme_agent.answer import (Answer, Citation, Claim, verify_answer,
                             verify_citation)


def _claim(unit_id, quote, status="current"):
    return Claim(statement="x", citations=[Citation(unit_id=unit_id, quote=quote)],
                 status=status, superseded_by="", as_of="")


def test_exact_quote_verifies(store):
    v = verify_citation(store, Citation(unit_id="T06.s0008",
                                        quote="shelf life is populated on forty-eight percent"))
    assert v.ok and v.match == "exact"


def test_whitespace_and_case_do_not_break_a_real_quote(store):
    v = verify_citation(store, Citation(unit_id="T06.s0008",
                                        quote="And  SHELF   life is populated on forty-eight percent."))
    assert v.ok and v.match == "exact"


def test_fabricated_quote_is_rejected(store):
    v = verify_citation(store, Citation(unit_id="T06.s0008",
                                        quote="shelf life is populated on ninety percent"))
    assert not v.ok and "does not appear" in v.problem


def test_fabricated_unit_id_is_rejected(store):
    v = verify_citation(store, Citation(unit_id="E99.m01", quote="anything"))
    assert not v.ok and "fabricated" in v.problem


def test_citation_metadata_comes_from_the_index_not_the_model(store):
    v = verify_citation(store, Citation(unit_id="E07.m03", quote="I can purge the landing zone"))
    assert v.speaker == "Kwame Boateng"
    assert v.date.startswith("2025-11-24")
    assert "message 3 of 4" in v.reference


def test_claim_with_no_citation_is_reported_unsupported(store):
    ans = Answer(answer="x", claims=[Claim(statement="unsourced", citations=[],
                                           status="current", superseded_by="", as_of="")],
                 gaps=[], abstentions=[], confidence="high", method_note="")
    rep = verify_answer(store, ans)
    assert rep.unsupported_claims == ["unsourced"]
    assert not rep.ok


def test_claim_resting_on_a_cut_off_statement_raises_a_warning(store):
    ans = Answer(answer="x", claims=[_claim("T06.s0018", "of which roughly if you...")],
                 gaps=[], abstentions=[], confidence="high", method_note="")
    rep = verify_answer(store, ans)
    assert any("cut off" in w for w in rep.warnings)


def test_internal_recording_is_flagged(store):
    u = store.doc_units("transcripts/09_2025-02-12_INTERNAL-account-review")[1]
    ans = Answer(answer="x", claims=[_claim(u.unit_id, u.text[:40])],
                 gaps=[], abstentions=[], confidence="high", method_note="")
    rep = verify_answer(store, ans)
    assert any("internal RELEX-only" in w for w in rep.warnings)
