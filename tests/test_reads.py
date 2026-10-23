"""The read tools: a note in context, search, and queries over front matter."""

import pytest

from orbit import reads, writes
from orbit.errors import OrbitError

EMAIL = "2026-10-14 Email – AW Offerte Wartungsvertrag 2027"


def test_context_of_a_person(crm, example):
    found = reads.context(crm, "per_01M4WNN540CGMAHYXV1R90AA5V")
    assert (found["name"], found["type"], found["path"]) == (
        "Hans Müller",
        "person",
        str(example / "01_People/Hans Müller.md"),
    )
    assert found["fields"]["job_title"] == "Leiter Einkauf"
    assert [o["confidence"] for o in found["observations"]] == ["high", "medium"]
    assert found["observations"][0] == {
        "date": "2026-10-14",
        "statement": "On first-name terms with Tobias (du)",
        "evidence": "Lieber Tobias",
        "source": f"[[{EMAIL}]]",
        "confidence": "high",
    }
    assert found["last_changes"] == {
        "created": {
            "date": "2026-10-14",
            "source": f"[[{EMAIL}]]",
            "reason": "no candidate matched hans.mueller@acme-ag.example",
        }
    }
    assert found["links_out"] == [
        {"field": "org", "name": "Acme AG", "id": "org_01M4WNN44RG8NK7BC7R54A18GA", "type": "organization"},
        {"field": "colleague_of", "name": "Anna Keller", "id": "per_01M4WNN638ANBSPNBRJV8CW5V4", "type": "person"},
    ]
    assert [(i["name"], i["via"]) for i in found["links_in"]] == [
        ("Anna Keller", ["colleague_of"]),
        ("Wartungsvertrag 2027", ["people"]),
    ]
    (interaction,) = found["interactions"]
    assert interaction == {
        "id": "int_01M4WNN35GDE3YGJ5DYM2SWSQA",
        "type": "interaction",
        "name": EMAIL,
        "via": ["from"],
        "date": "2026-10-14T09:32:00+02:00",
        "kind": "email",
        "direction": "inbound",
        "subject": "AW: Offerte Wartungsvertrag 2027",
    }
    assert [(t["name"], t["status"], t["due"]) for t in found["open_tasks"]] == [
        ("Send revised offer for Wartungsvertrag 2027", "open", "2026-11-01")
    ]
    assert [r["name"] for r in found["pending_reviews"]] == ["2026-10-18 Duplicate – Hans and Hans Müller"]
    assert found["sections"] == {"Notes": ""}


def test_context_by_name_or_link(crm):
    assert (
        reads.context(crm, "Acme AG")["id"]
        == reads.context(crm, "[[acme ag]]")["id"]
        == "org_01M4WNN44RG8NK7BC7R54A18GA"
    )


def test_context_of_an_interaction_has_its_sections(crm):
    found = reads.context(crm, EMAIL)
    assert found["sections"]["Key quote"] == "> Das Budget für 2027 ist freigegeben."
    assert found["sections"]["Action items"].count("[[") == 2
    assert "observations" not in found
    assert "last_changes" not in found


def test_context_of_an_interaction_shows_its_thread(crm):
    assert "thread" not in reads.context(crm, EMAIL)  # alone in its thread
    reply = writes.log_interaction(
        crm, "email", "2026-10-15", subject="Re", in_reply_to="<20261014093200.4711@acme-ag.example>"
    )
    for ref in (EMAIL, reply["id"]):
        thread = reads.context(crm, ref)["thread"]
        assert [i["name"] for i in thread["interactions"]] == [EMAIL, reply["name"]]
        assert len(thread["open_tasks"]) == 2
    assert "thread" not in reads.context(crm, "Hans Müller")


def test_a_thread_lists_only_topics_that_are_links(crm):
    note = crm.vault.path(f"03_Interactions/2026/2026-10/{EMAIL}.md")
    note.write_text(
        note.read_text(encoding="utf-8").replace('  - "[[Wartungsvertrag 2027]]"', "  - true\n  -"), "utf-8"
    )
    crm.refresh()
    writes.log_interaction(
        crm, "email", "2026-10-15", subject="Re", in_reply_to="<20261014093200.4711@acme-ag.example>"
    )
    assert reads.context(crm, EMAIL)["thread"]["topics"] == []


def test_context_since(crm):
    found = reads.context(crm, "Hans Müller", since="2026-10-15")
    assert "observations" not in found
    assert found["interactions"] == []
    assert reads.context(crm, "Hans Müller", since="2026-10-14T00:00:00+02:00")["interactions"]


def test_tasks_done_are_not_open(crm):
    task = crm.vault.path("04_Tasks/Send revised offer for Wartungsvertrag 2027.md")
    task.write_text(task.read_text(encoding="utf-8").replace("status: open", "status: done"), encoding="utf-8")
    crm.refresh()
    assert reads.context(crm, "Hans Müller")["open_tasks"] == []


@pytest.mark.parametrize(
    "ref, since, message",
    [
        ("Nobody", None, "id_or_name: no note has the id or name 'Nobody'. Find it with resolve_entity"),
        ("per_01M4WNN540CGMAHYXV1R90AA5X", None, "no note has the id or name"),
        ("", None, "id_or_name: give an id"),
        ("Hans Müller", "last week", "since: 'last week' is not a date"),
    ],
)
def test_context_errors(crm, ref, since, message):
    with pytest.raises(OrbitError, match=message):
        reads.context(crm, ref, since)


def test_search_matches_names_however_written(crm):
    hits = reads.search(crm, "Mueller")
    assert [h["name"] for h in hits[:2]] == ["Hans Müller", "Hans"]
    assert hits[0]["job_title"] == "Leiter Einkauf"
    assert hits[0]["matched"] == "words"
    assert [h["name"] for h in reads.search(crm, "Müller", type="person")] == ["Hans Müller", "Hans"]


def test_search_job_titles_addresses_and_text(crm):
    assert [h["name"] for h in reads.search(crm, "einkauf")] == ["Hans Müller"]
    assert [h["name"] for h in reads.search(crm, "acme-ag.example", type="organization")] == ["Acme AG"]
    assert [h["name"] for h in reads.search(crm, "Pikettdienst")] == ["Send revised offer for Wartungsvertrag 2027"]
    assert reads.search(crm, "Bodensee", type="interaction")[0]["subject"] == "Segelwochenende Bodensee"


def test_search_falls_back_to_any_word_then_to_sound(crm):
    assert [h["name"] for h in reads.search(crm, "Anna Nobody", type="person")] == ["Anna Keller"]
    (hit,) = reads.search(crm, "Möller")
    assert (hit["name"], hit["matched"], hit["score"]) == ("Hans Müller", "sound", 0.0)
    assert reads.search(crm, "Möller", type="task") == []


def test_search_limit(crm):
    assert len(reads.search(crm, "Hans", limit=1)) == 1
    assert len(reads.search(crm, "Hans Möller Keller", limit=2)) == 2


@pytest.mark.parametrize(
    "query, type, message", [("", None, "query: the words"), ("--", None, "query"), ("x", "meeting", "type: one of")]
)
def test_search_errors(crm, query, type, message):
    with pytest.raises(OrbitError, match=message):
        reads.search(crm, query, type)


def names(result):
    return [r["name"] for r in result["results"]]


@pytest.mark.parametrize(
    "filters, found",
    [
        ({"org": "[[Acme AG]]"}, ["Anna Keller", "Hans Müller"]),
        ({"org": "acme ag"}, ["Anna Keller", "Hans Müller"]),
        ({"colleague_of": "Hans Müller"}, ["Anna Keller"]),
        ({"context": ["personal", "both"]}, ["Hans"]),
        ({"last_contact": {"<": "2026-10-15"}}, ["Anna Keller", "Hans Müller"]),
        ({"last_contact": {">=": "2026-10-15", "<=": "2026-10"}}, ["Hans"]),
        ({"me": {"exists": True}}, ["Me"]),
        ({"me": {"exists": False}, "review_status": {"not": "needs_review"}}, ["Anna Keller", "Hans Müller"]),
        ({"me": True}, ["Me"]),
        ({}, ["Anna Keller", "Hans Müller", "Hans", "Me"]),
    ],
)
def test_list_people(crm, filters, found):
    assert names(reads.list_entities(crm, "person", filters)) == found


def test_list_open_tasks_due_before_a_date(crm):
    result = reads.list_entities(crm, "task", {"status": ["open", "waiting"], "due": {"<": "2026-11-01"}})
    assert names(result) == ["Anna Keller to follow up on the technical clarification"]
    assert result["results"][0]["fields"]["owner"] == "[[Anna Keller]]"


def test_list_sorted(crm):
    assert names(reads.list_entities(crm, "person", sort="-last_contact")) == [
        "Hans",
        "Anna Keller",
        "Hans Müller",
        "Me",
    ]
    assert names(reads.list_entities(crm, "task", sort="due")) == [
        "Anna Keller to follow up on the technical clarification",
        "Send revised offer for Wartungsvertrag 2027",
    ]


def test_list_limit_and_total(crm):
    result = reads.list_entities(crm, "person", limit=1)
    assert (result["total"], len(result["results"])) == (4, 1)


def test_list_by_links_in_any_spelling(crm):
    assert names(reads.list_entities(crm, "person", {"org": ["ACME AG", "[[Beta GmbH]]"]})) == [
        "Anna Keller",
        "Hans Müller",
    ]
    assert names(reads.list_entities(crm, "person", {"org": "Beta GmbH"})) == []
    assert names(reads.list_entities(crm, "person", {"org": {"not": "[[Acme AG]]"}})) == ["Hans", "Me"]
    found = reads.list_entities(crm, "interaction", {"from": "Hans Müller", "orgs": "Acme AG"})
    assert names(found) == ["2026-10-14 Email – AW Offerte Wartungsvertrag 2027"]


def test_list_by_a_field_tobias_added(crm):
    hans = crm.vault.path("01_People/Hans.md")
    hans.write_text(hans.read_text(encoding="utf-8").replace("context:", "boat: Lacustre\ncontext:"), encoding="utf-8")
    crm.refresh()
    assert names(reads.list_entities(crm, "person", {"boat": "Lacustre"})) == ["Hans"]


@pytest.mark.parametrize(
    "type, filters, sort, message",
    [
        ("meeting", None, None, "type: one of"),
        ("person", {"mood": "good"}, None, "person has no field 'mood'"),
        ("person", None, "-mood", "person has no field 'mood'"),
        ("person", {"last_contact": {"~": "x"}}, None, "last_contact: unknown condition '~'"),
        ("person", ["org"], None, "filters: an object"),
    ],
)
def test_list_errors(crm, type, filters, sort, message):
    with pytest.raises(OrbitError, match=message):
        reads.list_entities(crm, type, filters, sort)


def test_context_of_a_note_gone_or_broken_says_which_and_what_to_do(crm):
    crm.vault.path("01_People/Hans.md").unlink()
    with pytest.raises(OrbitError, match=r"01_People/Hans\.md is gone from the vault"):
        reads.context(crm, "Hans")
    note = crm.vault.path("01_People/Anna Keller.md")
    note.write_text(note.read_text(encoding="utf-8").replace("context: professional", "team:\n  name: x"), "utf-8")
    with pytest.raises(
        OrbitError, match=r"01_People/Anna Keller\.md can't be read: line \d+: nested mappings .*; fix it by hand"
    ):
        reads.context(crm, "Anna Keller")


def test_limits_below_zero_mean_none(crm):
    assert reads.search(crm, "Hans", limit=-1) == []
    result = reads.list_entities(crm, "person", limit=-1)
    assert (result["total"], result["results"]) == (4, [])
