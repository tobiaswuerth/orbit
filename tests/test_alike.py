"""A new note like one already there is refused when it is created, with the notes it is like, so that duplicates
never come about, whoever creates them and however many create them at once. The caller then names the note it
means, or says the new one is a different one, which is recorded on both."""

import pytest

from orbit import reads, writes
from orbit.errors import OrbitError

CHAT = "Max in chat, 2026-10-22"


def fields(crm, ref):
    return reads.context(crm, ref)["fields"]


def test_a_new_person_named_like_one_there_is_refused(crm):
    with pytest.raises(OrbitError, match=r"alike.*\[\[Hans Müller\]\] \(per_\w+, 0\.85: same name") as refused:
        writes.upsert_person(crm, "new", {"name": "Hans Müller", "emails": ["h.m@other.example"]}, CHAT, "new here")
    assert "call again with its id as match" in str(refused.value)
    assert "distinct_from" in str(refused.value)


def test_a_new_person_said_to_be_another_is_created_and_recorded_on_both(crm):
    hans = crm.find("Hans Müller")
    result = writes.upsert_person(
        crm, "new", {"name": "Hans Müller", "emails": ["h.m@other.example"]}, CHAT, "another Hans Müller",
        distinct_from=[hans.id],
    )  # fmt: skip
    other = result["name"]
    assert fields(crm, other)["distinct_from"] == ["[[Hans Müller]]"]
    assert f"[[{other}]]" in fields(crm, "Hans Müller")["distinct_from"]


def test_a_new_person_one_is_unsure_of_is_created_provisional(crm):
    result = writes.upsert_person(
        crm, "new", {"name": "Hans Müller", "emails": ["h.m@other.example"]}, CHAT, "maybe Hans Müller",
        provisional=True,
    )  # fmt: skip
    assert fields(crm, result["name"])["review_status"] == "needs_review"


def test_a_person_unlike_any_is_created(crm):
    result = writes.upsert_person(crm, "new", {"name": "Lea Frei"}, CHAT, "no candidate")
    assert result["created"] is True


def test_a_topic_named_with_most_of_the_words_of_one_is_refused(crm):
    # Two runs at once created "Modulprüfung MP 254" and "Modulprüfung Modul 254".
    writes.upsert_topic(crm, "new", {"name": "Modulprüfung MP 254"}, CHAT)
    with pytest.raises(OrbitError, match=r"alike.*\[\[Modulprüfung MP 254\]\]"):
        writes.upsert_topic(crm, "new", {"name": "Modulprüfung Modul 254"}, CHAT)
    writes.upsert_topic(crm, "new", {"name": "Modulprüfung Modul 254"}, CHAT, distinct_from=["Modulprüfung MP 254"])
    assert fields(crm, "Modulprüfung MP 254")["distinct_from"] == ["[[Modulprüfung Modul 254]]"]


@pytest.mark.parametrize("name", ["Acme", "ACME AG", "Acme Services"])
def test_an_organization_named_like_one_there_is_refused(crm, name):
    with pytest.raises(OrbitError, match=r"alike.*\[\[Acme AG\]\]"):
        writes.upsert_organization(crm, "new", {"name": name}, CHAT, "new here")


def test_an_organization_named_by_the_initials_of_one_is_refused(crm):
    writes.upsert_organization(crm, "new", {"name": "Ausbildungszentrum Zürcher Oberland"}, CHAT, "no candidate")
    with pytest.raises(OrbitError, match=r"alike.*\[\[Ausbildungszentrum Zürcher Oberland\]\].*initials"):
        writes.upsert_organization(crm, "new", {"name": "AZO"}, CHAT, "no candidate")


def test_distinct_from_names_notes_of_the_same_type(crm):
    with pytest.raises(OrbitError, match=r"distinct_from: \[\[Acme AG\]\] is an organization, not a person"):
        writes.upsert_person(crm, "new", {"name": "Hans Müller"}, CHAT, "x", distinct_from=["Acme AG"])
