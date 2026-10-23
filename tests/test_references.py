"""create_missing_references: links to notes not written yet, mapped to an alias or given a stub note."""

from orbit import reads, upkeep
from orbit.lint import lint

NOTHING_DONE = {"dry_run": False, "created": [], "mapped": [], "skipped": [], "links_left": [], "changed": []}


def edit(crm, path, old, new):
    note = crm.vault.path(path)
    note.write_text(note.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")
    crm.refresh({path})


def fields(crm, ref):
    return reads.context(crm, ref)["fields"]


def test_a_link_in_a_typed_field_gets_a_stub_note(crm):
    edit(crm, "01_People/Anna Keller.md", '"[[Acme AG]]"', '"[[Acme Ltd]]"')
    result = upkeep.create_missing_references(crm)
    (created,) = result["created"]
    assert (created["link"], created["type"], created["name"]) == ("[[Acme Ltd]]", "organization", "Acme Ltd")
    assert created["path"] == str(crm.vault.path("02_Organizations/Acme Ltd.md"))
    assert (
        crm.vault.path("02_Organizations/Acme Ltd.md")
        .read_text(encoding="utf-8")
        .endswith(
            "## Notes\n\n## History\n- 2026-10-22 · created: a stub for the links to it from 1 note · [[Anna Keller]]\n"
        )
    )
    assert (result["mapped"], result["skipped"]) == ([], [])
    assert [c["name"] for c in result["changed"]] == ["Acme Ltd"]
    assert lint(crm)["issues"] == []


def test_a_stub_person_needs_review(crm):
    edit(
        crm,
        "05_Topics/Wartungsvertrag 2027.md",
        '  - "[[Anna Keller]]"',
        '  - "[[Anna Keller]]"\n  - "[[Peter Brand]]"',
    )
    (created,) = upkeep.create_missing_references(crm)["created"]
    assert created["type"] == "person"
    assert fields(crm, "Peter Brand")["review_status"] == "needs_review"


def test_a_link_to_an_alias_is_mapped_to_its_note(crm):
    edit(crm, "05_Topics/Wartungsvertrag 2027.md", '  - "[[Anna Keller]]"', '  - "[[Anna Keller]]"\n  - "[[hansi]]"')
    result = upkeep.create_missing_references(crm)
    assert result["mapped"] == [{"link": "[[hansi]]", "to": "[[Hans]]", "notes": 1}]
    assert fields(crm, "Wartungsvertrag 2027")["people"] == ["[[Hans Müller]]", "[[Anna Keller]]", "[[Hans]]"]
    assert result["created"] == []


def test_what_it_cant_decide_is_left_and_said(crm):
    edit(crm, "01_People/Hans Müller.md", "## Notes\n", "## Notes\nMet [[Peter Brand]], see ![[card.png]].\n")
    edit(crm, "01_People/Anna Keller.md", '"[[Acme AG]]"', '"[[Brand]]"')
    edit(crm, "05_Topics/Wartungsvertrag 2027.md", '  - "[[Anna Keller]]"', '  - "[[Anna Keller]]"\n  - "[[Brand]]"')
    for path in ("01_People/Hans.md", "01_People/Anna Keller.md"):
        edit(crm, path, "context:", "aliases:\n  - HM\ncontext:" if "Anna" in path else "context:")
    edit(crm, "01_People/Hans.md", "  - Hansi", "  - Hansi\n  - HM")
    edit(crm, "02_Organizations/Acme AG.md", "## Notes\n", "## Notes\nAsk [[HM]].\n")
    result = upkeep.create_missing_references(crm)
    assert result["skipped"] == [
        {"link": "[[Brand]]", "reason": "linked as an organization and as a person; create it with upsert_*"},
        {"link": "[[HM]]", "reason": "an alias of [[Anna Keller]] and [[Hans]]; link one of them"},
        {"link": "[[Peter Brand]]", "reason": "only linked in text, so its type is unknown; create it with upsert_*"},
    ]
    assert (result["created"], result["mapped"], result["changed"]) == ([], [], [])


def test_a_dry_run_changes_nothing(crm):
    edit(crm, "01_People/Anna Keller.md", '"[[Acme AG]]"', '"[[Acme Ltd]]"')
    edit(crm, "05_Topics/Wartungsvertrag 2027.md", '  - "[[Anna Keller]]"', '  - "[[Anna Keller]]"\n  - "[[Hansi]]"')
    result = upkeep.create_missing_references(crm, dry_run=True)
    assert result["dry_run"] is True
    assert result["created"] == [{"link": "[[Acme Ltd]]", "type": "organization", "name": "Acme Ltd"}]
    assert result["mapped"] == [{"link": "[[Hansi]]", "to": "[[Hans]]", "notes": 1}]
    assert not crm.vault.path("02_Organizations/Acme Ltd.md").exists()
    assert "[[Hansi]]" in fields(crm, "Wartungsvertrag 2027")["people"]
    assert result["changed"] == []


def test_a_name_that_cant_be_a_file_name(crm):
    edit(crm, "01_People/Anna Keller.md", '"[[Acme AG]]"', '"[[Acme: Holding]]"')
    (created,) = upkeep.create_missing_references(crm)["created"]
    assert created["name"] == "Acme Holding"
    assert fields(crm, "Anna Keller")["org"] == "[[Acme Holding]]"
    assert fields(crm, "Acme Holding")["name"] == "Acme: Holding"


def test_links_in_a_note_that_cant_be_read_are_listed_as_left(crm):
    edit(crm, "05_Topics/Wartungsvertrag 2027.md", '  - "[[Anna Keller]]"', '  - "[[Anna Keller]]"\n  - "[[hansi]]"')
    crm.vault.write("01_People/Broken.md", "---\ntype: person\norg:\n  name: Acme\n---\nAsk [[hansi]].\n")
    crm.refresh({"01_People/Broken.md"})
    result = upkeep.create_missing_references(crm)
    assert result["mapped"] == [{"link": "[[hansi]]", "to": "[[Hans]]", "notes": 2}]
    (left,) = result["links_left"]
    assert (left["note"], left["path"]) == ("Broken", str(crm.vault.path("01_People/Broken.md")))
    assert "can't be read" in left["reason"]
    assert "[[Hans]]" in fields(crm, "Wartungsvertrag 2027")["people"]


def test_a_link_to_a_file_that_is_not_a_note_is_not_missing(crm):
    edit(crm, "01_People/Hans Müller.md", "## Notes\n", "## Notes\nSee [[AGENTS]] and ![[People.base]].\n")
    assert upkeep.create_missing_references(crm) == NOTHING_DONE


def test_nothing_missing_nothing_done(crm):
    assert upkeep.create_missing_references(crm) == NOTHING_DONE
