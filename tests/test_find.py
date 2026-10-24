"""Finding the note a caller names: by id, file name, address, and also by the name its front matter gives or an alias,
if one note alone has it; and, for a note of the wrong type, where it belongs instead."""

import pytest

from orbit import reads, writes
from orbit.errors import OrbitError

CHAT = "Max in chat, 2026-10-22"
SAILING = "2026-10-18 Email – Segelwochenende Bodensee"


def fields(crm, ref):
    return reads.context(crm, ref)["fields"]


def test_the_owner_is_found_by_their_name(crm):
    # Agents named the owner "Max Doe", whose note is Me.md.
    writes.link_entities(crm, SAILING, "mentioned", "Max", CHAT)
    assert "[[Me]]" in fields(crm, SAILING)["mentioned"]


def test_a_note_is_found_by_an_alias(crm):
    writes.link_entities(crm, SAILING, "mentioned", "Hansi", CHAT)
    assert "[[Hans]]" in fields(crm, SAILING)["mentioned"]


def test_a_name_two_notes_answer_to_names_both(crm):
    crm.vault.write(
        "01_People/Johann.md",
        "---\ntype: person\nid: per_01M4WNN44RG8NK7BC7R54A18GD\nname: Johann\naliases:\n  - Hansi\n---\n",
    )
    crm.refresh()
    with pytest.raises(OrbitError, match=r"to: 'Hansi' is the name or an alias of \[\[Hans\]\] and \[\[Johann\]\]"):
        writes.link_entities(crm, SAILING, "mentioned", "Hansi", CHAT)


@pytest.mark.parametrize(
    "relation, ref, message",
    [
        ("from", "Acme AG", r"to: \[\[Acme AG\]\] is an organization, not a person: name it under orgs"),
        ("topics", "Acme AG", r"to: \[\[Acme AG\]\] is an organization, not a topic: name it under orgs"),
        (
            "orgs",
            "Wartungsvertrag 2027",
            r"to: \[\[Wartungsvertrag 2027\]\] is a topic, not an organization: name it under topics",
        ),
        ("orgs", "Anna Keller", r"to: \[\[Anna Keller\]\] is a person, not an organization: name it under from, to"),
    ],
)
def test_a_note_of_another_type_says_where_it_belongs(crm, relation, ref, message):
    with pytest.raises(OrbitError, match=message):
        writes.link_entities(crm, SAILING, relation, ref, CHAT)


def test_a_note_logged_in_the_wrong_field_says_where_it_belongs(crm):
    call = {"kind": "call", "date": "2026-10-20T08:15:00+02:00", "sender": "Anna Keller", "topics": ["Acme AG"]}
    with pytest.raises(
        OrbitError, match=r"topics: \[\[Acme AG\]\] is an organization, not a topic: name it under orgs"
    ):
        writes.log_interaction(crm, **call)


def test_a_note_of_another_type_elsewhere_gets_no_hint(crm):
    with pytest.raises(OrbitError, match=r"match: \[\[Acme AG\]\] is an organization, not a person$"):
        writes.upsert_person(crm, "Acme AG", {"job_title": "x"}, CHAT)


def test_a_name_written_otherwise_is_not_taken_for_one(crm):
    # The same words in another order, as resolve_entity finds them, are a candidate, not the note itself.
    with pytest.raises(OrbitError, match="no note has the id or name 'Müller, Hans'"):
        crm.find("Müller, Hans")
