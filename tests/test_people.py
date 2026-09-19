import pytest


@pytest.mark.parametrize("surface,expected", [
    ("Kwame Boateng", "Kwame Boateng"),
    ("Kwame", "Kwame Boateng"),
    ("Boateng", "Kwame Boateng"),
    ("k.boateng@relexsolutions.example", "Kwame Boateng"),
    ("KB", "Kwame Boateng"),
    ("Henrik Sørensen", "Henrik Sørensen"),
    ("Henrik Sorensen", "Henrik Sørensen"),      # diacritic-folded spelling
    ("henrik.sorensen@relexsolutions.example", "Henrik Sørensen"),
    ("Ana Duarte (RELEX)", "Ana Duarte"),
    ("Lena Fischer <lena.fischer@acme-org.example>", "Lena Fischer"),
])
def test_alias_resolution(registry, surface, expected):
    p = registry.resolve(surface)
    assert p is not None and p.display == expected


def test_unknown_speaker_is_not_resolved_to_anyone(registry):
    assert registry.resolve("Unknown Speaker") is None


def test_offroster_people_are_discovered(registry):
    """The README lists 15 people. The archive contains more, including staff
    who appear only as an email address."""
    displays = {p.display for p in registry.people.values()}
    assert {"Ahmed Nasser", "Elin Bergqvist", "Martina Reuss"} <= displays
    assert len(registry.people) > 15


def test_discovery_does_not_invent_people_from_prose(registry):
    displays = {p.display for p in registry.people.values()}
    for junk in ("The The", "She She", "Sollten Sie", "Project Manager", "Acme Org"):
        assert junk not in displays
