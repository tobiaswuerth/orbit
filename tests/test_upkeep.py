"""Upkeep: renaming notes, merging duplicates, and the links that follow them."""

import pytest

from orbit import reads, upkeep, writes
from orbit.errors import OrbitError
from orbit.lint import lint

CHAT = "Tobias in chat, 2026-10-22"
EMAIL = "2026-10-14 Email – AW Offerte Wartungsvertrag 2027"
SAILING = "2026-10-18 Email – Segelwochenende Bodensee"
REVIEW = "2026-10-18 Duplicate – Hans and Hans Müller"
HANS_ID, MUELLER_ID = "per_01M57ZJKJ8HWCPYDPQSTB9FCH9", "per_01M4WNN540CGMAHYXV1R90AA5V"


def text(crm, path):
    return crm.vault.path(path).read_text(encoding="utf-8")


def fields(crm, ref):
    return reads.context(crm, ref)["fields"]


def edit(crm, path, old, new):
    note = crm.vault.path(path)
    note.write_text(note.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")


# Links


@pytest.mark.parametrize(
    "line, rewritten",
    [
        ("see [[Hans]] and [[Hansi]]", "see [[Hans Brand]] and [[Hansi]]"),
        ("![[hans#Notes|his notes]]", "![[Hans Brand#Notes|his notes]]"),
        ("[[01_People/Hans.md]], [[Hans^block]]", "[[Hans Brand]], [[Hans Brand^block]]"),
        ("no links", "no links"),
    ],
)
def test_links_are_rewritten_in_any_form(line, rewritten):
    assert upkeep.rewrite_links(line, "Hans", "Hans Brand") == rewritten


# rename_entity


def test_renaming_a_person_moves_the_file_and_rewrites_every_link(crm):
    result = upkeep.rename(crm, "Hans", "Hans Brand", CHAT)
    assert (result["name"], result["path"]) == ("Hans Brand", str(crm.vault.path("01_People/Hans Brand.md")))
    assert not crm.vault.path("01_People/Hans.md").exists()
    found = fields(crm, HANS_ID)
    assert (found["name"], found["aliases"]) == ("Hans Brand", ["Hansi", "Hans"])
    assert text(crm, "01_People/Hans Brand.md").endswith(f"- 2026-10-22 · name: Hans → Hans Brand · {CHAT}\n")
    assert fields(crm, SAILING)["from"] == "[[Hans Brand]]"
    assert fields(crm, REVIEW)["candidates"] == ["[[Hans Brand]]", "[[Hans Müller]]"]
    assert {c["name"] for c in result["changed"]} == {"Hans Brand", SAILING, REVIEW}
    assert crm.find("Hans").name == "Hans Brand"  # the old name, an alias now, still finds it
    assert lint(crm)["issues"] == []


def test_renaming_a_task_rewrites_the_action_items_that_list_it(crm):
    upkeep.rename(crm, "Send revised offer for Wartungsvertrag 2027", "Send the revised offer", CHAT)
    assert "- [[Send the revised offer]]\n" in text(crm, f"03_Interactions/2026/2026-10/{EMAIL}.md")
    assert crm.vault.path("04_Tasks/Send the revised offer.md").exists()
    assert lint(crm)["issues"] == []


def test_an_interaction_is_renamed_in_its_folder(crm):
    result = upkeep.rename(crm, SAILING, "2026-10-18 Email – Segeln", CHAT)
    assert result["path"] == str(crm.vault.path("03_Interactions/2026/2026-10/2026-10-18 Email – Segeln.md"))
    assert fields(crm, "Hans")["last_contact"] == "2026-10-18"
    assert "[[2026-10-18 Email – Segeln]]" in text(crm, "01_People/Hans.md")


def test_renaming_rewrites_links_in_the_owners_notes_too(crm):
    edit(crm, "01_People/Anna Keller.md", "## Notes\n", "## Notes\nSails with [[Hans|Hansi]].\n")
    crm.refresh()
    upkeep.rename(crm, "Hans", "Hans Brand", CHAT)
    assert "## Notes\nSails with [[Hans Brand|Hansi]].\n" in text(crm, "01_People/Anna Keller.md")


def test_a_name_only_changing_case(crm):
    result = upkeep.rename(crm, "Acme AG", "ACME AG", CHAT)
    assert result["name"] == "ACME AG"
    assert fields(crm, "Hans Müller")["org"] == "[[ACME AG]]"


def test_renaming_to_the_same_name_changes_nothing(crm):
    assert upkeep.rename(crm, "Acme AG", "Acme AG", CHAT)["changed"] == []


@pytest.mark.parametrize(
    "ref, name, message",
    [
        ("Hans", "Hans Müller", r"a note called Hans Müller exists already: \[\[Hans Müller\]\]"),
        ("Hans", " ", "new_name: the note's new name"),
        ("Nobody", "X", "no note has the id or name 'Nobody'"),
    ],
)
def test_rename_refuses(crm, ref, name, message):
    with pytest.raises(OrbitError, match=message):
        upkeep.rename(crm, ref, name, CHAT)


# merge_entities


def test_merging_two_people(crm):
    result = upkeep.merge(crm, "Hans Müller", "Hans", CHAT)
    assert (result["id"], result["name"]) == (MUELLER_ID, "Hans Müller")
    assert not crm.vault.path("01_People/Hans.md").exists()
    assert crm.vault.path(".trash/Hans.md").read_text(encoding="utf-8").startswith(f"---\ntype: person\nid: {HANS_ID}")
    found = fields(crm, "Hans Müller")
    assert found["aliases"] == ["Hans", "Hansi"]
    assert found["emails"] == ["hans.mueller@acme-ag.example", "hansi.mueller@gmail.com"]
    assert found["context"] == "both"  # professional and personal
    assert (found["last_contact"], found["created"], found["review_status"]) == (
        "2026-10-18",
        "2026-10-14",
        "confirmed",
    )
    assert found["merged_from"] == [HANS_ID]
    page = text(crm, "01_People/Hans Müller.md")
    assert page.endswith(
        f"- 2026-10-18 · created: provisional, possibly [[Hans Müller]], see [[{REVIEW}]] · [[{SAILING}]]\n"
        f"- 2026-10-22 · merged: Hans ({HANS_ID}) · {CHAT}\n"
    )
    assert fields(crm, SAILING)["from"] == "[[Hans Müller]]"
    review = fields(crm, REVIEW)
    assert (review["decision"], review["candidates"]) == ("same", ["[[Hans Müller]]"])
    assert result["conflicts"] == []
    assert lint(crm)["issues"] == []


def test_a_merged_id_still_finds_the_note(crm):
    upkeep.merge(crm, "Hans Müller", "Hans", CHAT)
    assert crm.find(HANS_ID).name == "Hans Müller"
    assert reads.context(crm, HANS_ID)["id"] == MUELLER_ID


def test_the_older_id_is_kept(crm):
    result = upkeep.merge(crm, "Hans", "Hans Müller", CHAT)
    assert (result["id"], result["name"]) == (MUELLER_ID, "Hans")
    found = fields(crm, "Hans")
    assert (found["id"], found["merged_from"], found["created"]) == (MUELLER_ID, [HANS_ID], "2026-10-14")
    assert crm.find(HANS_ID).name == crm.find(MUELLER_ID).name == "Hans"
    assert fields(crm, "Anna Keller")["colleague_of"] == ["[[Hans]]"]


def test_differing_values_are_kept_and_go_to_review(crm):
    writes.set_fields(crm, "Hans", {"location": "Romanshorn"}, CHAT, "2026-10-22")
    writes.upsert_person(crm, "Hans Müller", {"location": "Winterthur"}, CHAT)
    result = upkeep.merge(crm, "Hans Müller", "Hans", CHAT)
    assert result["conflicts"] == [{"field": "location", "kept": "Winterthur", "dropped": "Romanshorn"}]
    assert fields(crm, "Hans Müller")["location"] == "Winterthur"
    review = reads.context(crm, result["review"]["id"])
    assert review["fields"]["kind"] == "other"
    assert review["fields"]["candidates"] == ["[[Hans Müller]]"]
    assert review["sections"]["Evidence for"] == "- location: kept Winterthur"
    assert review["sections"]["Evidence against"] == "- location: Hans had Romanshorn"


def test_blank_fields_are_filled_and_the_owners_writing_is_kept(crm):
    edit(crm, "01_People/Hans.md", "## Notes\n", "## Notes\nOwns a boat.\n\n## Family\n- two kids\n")
    edit(crm, "01_People/Hans.md", "context:", "boat: Lacustre\ncontext:")
    crm.refresh()
    writes.add_observation(crm, "Hans", "Sails", "Segeln", "high", f"[[{SAILING}]]")
    upkeep.merge(crm, "Hans Müller", "Hans", CHAT)
    page = text(crm, "01_People/Hans Müller.md")
    assert "## Notes\nFrom Hans, merged on 2026-10-22:\nOwns a boat.\n\n## Observations" in page
    assert "## Family\nFrom Hans, merged on 2026-10-22:\n- two kids\n" in page
    assert f"- 2026-10-18 · Sails · «Segeln» · [[{SAILING}]] · high\n" in page
    assert fields(crm, "Hans Müller")["boat"] == "Lacustre"


def test_a_link_between_the_two_doesnt_become_a_link_to_itself(crm):
    writes.link_entities(crm, "Hans", "colleague_of", "Hans Müller", CHAT)
    upkeep.merge(crm, "Hans Müller", "Hans", CHAT)
    assert fields(crm, "Hans Müller")["colleague_of"] == ["[[Anna Keller]]"]
    assert fields(crm, "Anna Keller")["colleague_of"] == ["[[Hans Müller]]"]


def test_merging_organizations_and_topics(crm):
    # Duplicates as hand edits or an older orbit left them: orbit refuses to create one alike.
    crm.vault.write(
        "02_Organizations/ACME.md",
        "---\ntype: organization\nid: org_01M4WNN44RG8NK7BC7R54A18GB\nname: ACME\ndomains:\n  - acme.example\n---\n",
    )
    crm.vault.write(
        "05_Topics/Wartung.md", "---\ntype: topic\nid: top_01M4WNN44RG8NK7BC7R54A18GC\nname: Wartung\n---\n"
    )
    crm.refresh()
    writes.link_entities(crm, "Hans", "org", "ACME", CHAT)
    result = upkeep.merge(crm, "Acme AG", "ACME", CHAT)
    assert fields(crm, "Acme AG")["domains"] == ["acme-ag.example", "acme.example"]
    assert fields(crm, "Hans")["org"] == "[[Acme AG]]"
    assert result["name"] == "Acme AG"
    upkeep.merge(crm, "Wartungsvertrag 2027", "Wartung", CHAT)
    assert fields(crm, "Wartungsvertrag 2027")["aliases"] == ["Wartung"]


def test_a_second_merge_into_the_trash_keeps_both(crm):
    crm.vault.write(".trash/Hans.md", "an older deleted note\n")
    upkeep.merge(crm, "Hans Müller", "Hans", CHAT)
    assert crm.vault.path(".trash/Hans.md").read_text(encoding="utf-8") == "an older deleted note\n"
    assert crm.vault.path(".trash/Hans (2).md").exists()


@pytest.mark.parametrize(
    "keep, drop, message",
    [
        ("Hans", "Hans", "keep and drop are the same note"),
        ("Hans", "Acme AG", r"drop: \[\[Acme AG\]\] is an organization, not a person"),
        (EMAIL, SAILING, "is an interaction, not a person or an organization or a topic"),
        ("Hans Müller", "Me", "Me.md can't be merged into another note"),
    ],
)
def test_merge_refuses(crm, keep, drop, message):
    with pytest.raises(OrbitError, match=message):
        upkeep.merge(crm, keep, drop, CHAT)


def test_people_recorded_as_different_arent_merged(crm):
    path = f"90_Review/{REVIEW}.md"
    edit(crm, path, "decision: pending", "decision: different")
    crm.refresh({path})
    with pytest.raises(OrbitError) as refused:
        upkeep.merge(crm, "Hans Müller", "Hans", CHAT)
    assert str(refused.value) == (
        "[[Hans Müller]] and [[Hans]] are recorded as different people; only the owner can say otherwise: "
        "propose_review a duplicate, which returns their answer if they gave one, and their yes merges the two"
    )


# Reviews decided same


def test_a_review_decided_same_merges_into_the_older_note(crm):
    path = f"90_Review/{REVIEW}.md"
    edit(crm, path, "decision: pending", "decision: same")
    crm.refresh({path})
    assert not crm.vault.path("01_People/Hans.md").exists()
    found = fields(crm, "Hans Müller")
    assert found["merged_from"] == [HANS_ID]
    assert f"- 2026-10-22 · merged: Hans ({HANS_ID}) · [[{REVIEW}]]\n" in text(crm, "01_People/Hans Müller.md")
    assert fields(crm, REVIEW)["candidates"] == ["[[Hans Müller]]"]
    crm.refresh()  # applied once
    assert lint(crm)["issues"] == []


def test_a_review_decided_same_that_cant_be_merged_is_reported(crm):
    edit(crm, "01_People/Hans.md", f"id: {HANS_ID}\n", "")
    path = f"90_Review/{REVIEW}.md"
    edit(crm, path, "decision: pending", "decision: same")
    crm.refresh()
    assert crm.vault.path("01_People/Hans.md").exists()
    (issue,) = [i for i in lint(crm)["issues"] if i["rule"] == "not applied"]
    assert issue["note"] == REVIEW
    assert issue["message"] == (
        "decided same, but orbit couldn't merge them: keep: [[Hans]] has no id yet; lint_vault with fix gives it one"
    )


# People linked to their address's organization


def person(crm, name, *emails, extra=""):
    listed = "".join(f"  - {e}\n" for e in emails)
    crm.vault.write(
        f"01_People/{name}.md", f"---\ntype: person\nid: {ULIDS[name]}\nname: {name}\nemails:\n{listed}{extra}---\n"
    )


ULIDS = {"Lea Frei": "per_01M4WNN44RG8NK7BC7R54A18H1", "Max Muster": "per_01M4WNN44RG8NK7BC7R54A18H2",
         "Ida Graf": "per_01M4WNN44RG8NK7BC7R54A18H3"}  # fmt: skip


def test_people_without_an_org_are_linked_to_their_address_s_organization(crm):
    # People created before their organization, or by an import that left the org out, floated without it.
    person(crm, "Lea Frei", "lea@acme-ag.example")
    person(crm, "Max Muster", "max@gmail.com", "max@students.acme-ag.example")
    person(crm, "Ida Graf", "ida@acme-ag.example", extra='org: "[[Beta AG]]"\n')
    crm.refresh()
    planned = upkeep.link_by_domain(crm, dry_run=True)
    assert planned["linked"] == [
        {"person": "[[Lea Frei]]", "org": "[[Acme AG]]", "address": "lea@acme-ag.example"},
        {"person": "[[Max Muster]]", "org": "[[Acme AG]]", "address": "max@students.acme-ag.example"},
    ]
    assert (planned["changed"], "org" in fields(crm, "Lea Frei")) == ([], False)
    done = upkeep.link_by_domain(crm)
    assert (fields(crm, "Max Muster")["org"], len(done["changed"])) == ("[[Acme AG]]", 2)
    assert "- 2026-10-22 · org: [[Acme AG]] · the address max@students.acme-ag.example\n" in text(
        crm, "01_People/Max Muster.md")  # fmt: skip
    assert fields(crm, "Ida Graf")["org"] == "[[Beta AG]]"
    assert "org" not in fields(crm, "Me")
    assert upkeep.link_by_domain(crm)["linked"] == []  # done once


def test_me_keeps_its_name(crm):
    with pytest.raises(OrbitError, match=r"Me.md keeps its name: notes link to the owner as \[\[Me\]\]"):
        upkeep.rename(crm, "Me", "Tobias", CHAT)


def test_fields_other_than_text_are_left_as_they_are(crm):
    edit(crm, "01_People/Anna Keller.md", "context:", "pinned: true\nnothing:\ncontext:")
    edit(crm, "01_People/Anna Keller.md", "## Notes\n", "## Notes\nSee [[Hans]].\n")
    crm.refresh()
    upkeep.rename(crm, "Hans", "Hans Brand", CHAT)
    found = fields(crm, "Anna Keller")
    assert (found["pinned"], found["nothing"]) == (True, None)


def test_a_single_link_between_the_two_is_dropped(crm):
    writes.link_entities(crm, "Hans", "reports_to", "Hans Müller", CHAT)
    upkeep.merge(crm, "Hans Müller", "Hans", CHAT)
    assert "reports_to" not in fields(crm, "Hans Müller")


def test_notes_made_by_hand_without_dates_merge_too(crm):
    for name, ulid in (("Messe", "01M57ZJKJ8HWCPYDPQSTB9FCHA"), ("Fair", "01M57ZJKJ8HWCPYDPQSTB9FCHB")):
        crm.vault.write(f"05_Topics/{name}.md", f"---\ntype: topic\nid: top_{ulid}\nname: {name}\n---\n")
    crm.refresh()
    upkeep.merge(crm, "Messe", "Fair", CHAT)
    assert "created" not in fields(crm, "Messe")


def test_a_note_that_cant_be_read_doesnt_stop_links_from_following(crm):
    crm.vault.write("Inbox.md", "---\nteam:\n  name: x\n---\nAsk [[Hans]], or [[Hans Brand]].\n")
    crm.refresh({"Inbox.md"})
    result = upkeep.rename(crm, "Hans", "Hans Brand", CHAT)
    assert fields(crm, SAILING)["from"] == "[[Hans Brand]]"
    (left,) = result["links_left"]
    assert (left["note"], left["path"]) == ("Inbox", str(crm.vault.path("Inbox.md")))
    assert left["reason"].startswith("Inbox.md can't be read: line 3: nested mappings")
    merged = upkeep.merge(crm, "Hans Müller", "Hans Brand", CHAT)
    assert [n["note"] for n in merged["links_left"]] == ["Inbox"]
    assert fields(crm, SAILING)["from"] == "[[Hans Müller]]"


def test_notes_without_ids_cant_be_merged_until_they_have_them(crm):
    crm.vault.write("05_Topics/Messe.md", "---\ntype: topic\nname: Messe\n---\n")
    crm.refresh({"05_Topics/Messe.md"})
    with pytest.raises(OrbitError, match=r"drop: \[\[Messe\]\] has no id yet; lint_vault with fix gives it one"):
        upkeep.merge(crm, "Wartungsvertrag 2027", "Messe", CHAT)


def test_a_person_broken_since_indexed_is_left_unlinked_and_said(crm):
    person(crm, "Lea Frei", "lea@acme-ag.example")
    crm.refresh()
    edit(crm, "01_People/Lea Frei.md", "name: Lea Frei", "name: Lea Frei\nteam:\n  name: x")  # not indexed again yet
    result = upkeep.link_by_domain(crm)
    assert (result["linked"], [n["note"] for n in result["unreadable"]]) == ([], ["Lea Frei"])


def test_a_review_broken_since_it_was_indexed_is_left_and_said(crm):
    path = f"90_Review/{REVIEW}.md"
    edit(crm, path, "decision: pending", "decision: pending\nteam:\n  name: x")  # not indexed again yet
    result = upkeep.merge(crm, "Hans Müller", "Hans", CHAT)
    assert [n["note"] for n in result["links_left"]] == [REVIEW]
    assert fields(crm, SAILING)["from"] == "[[Hans Müller]]"


def test_a_review_broken_before_it_got_its_boxes_is_said(crm):
    path = f"90_Review/{REVIEW}.md"
    edit(crm, path, "answer_yes: false\nanswer_no: false\n", "")
    crm.index.refresh([path])  # indexed without its boxes, which aren't added yet
    edit(crm, path, "decision: pending", "decision: pending\nteam:\n  name: x")  # not indexed again yet
    upkeep.apply_reviews(crm)
    assert "can't be read" in crm.review_problems[path]


def test_the_owner_s_same_keeps_what_else_was_recorded_as_different(crm):
    edit(crm, "01_People/Hans.md", "review_status", 'distinct_from:\n  - "[[Hans Müller]]"\n  - "[[Anna Keller]]"\n'
         "review_status")  # fmt: skip
    crm.refresh()
    upkeep.merge(crm, "Hans Müller", "Hans", f"[[{REVIEW}]]", overrule=True)
    assert fields(crm, "Hans Müller")["distinct_from"] == ["[[Anna Keller]]"]
