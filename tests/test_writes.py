"""The write tools: their refusals, what they change, and what they leave alone."""

from pathlib import Path

import pytest

from orbit import reads, writes
from orbit.errors import OrbitError

EMAIL = "[[2026-10-14 Email – AW Offerte Wartungsvertrag 2027]]"
CHAT = "Tobias in chat, 2026-10-22"
HANS = "01_People/Hans Müller.md"


def text(crm, path):
    return crm.vault.path(path).read_text(encoding="utf-8")


def fields(crm, ref):
    return reads.context(crm, ref)["fields"]


# upsert_person


def test_new_is_refused_for_a_known_address(crm):
    with pytest.raises(OrbitError) as error:
        writes.upsert_person(crm, "new", {"name": "H. Müller", "emails": ["Hans.Mueller@acme-ag.example"]}, CHAT, "x")
    assert str(error.value) == (
        "emails: hans.mueller@acme-ag.example belongs to [[Hans Müller]] (per_01M4WNN540CGMAHYXV1R90AA5V). If this is "
        'the same person, call upsert_person with match "per_01M4WNN540CGMAHYXV1R90AA5V"; if not, leave the address '
        "out."
    )


@pytest.mark.parametrize(
    "match, given, reason, message",
    [
        ("new", {"name": "Info", "emails": ["info@acme-ag.example"]}, "x", "info@acme-ag.example is a role address"),
        ("new", {"emails": ["x@y.example"]}, "x", 'a new person needs a "name"'),
        ("new", {"name": "X"}, None, "resolution_reason: say why this is a new person"),
        (
            "new",
            {"name": "X", "last_contact": "2026-10-01"},
            "x",
            "last_contact: orbit sets it itself; log_interaction",
        ),
        ("new", {"name": "X", "created": "2026-10-01"}, "x", "created: orbit sets it itself$"),
        ("new", {"name": "X", "mood": "good"}, "x", "person has no field 'mood'"),
        ("new", {"name": "X", "org": "Beta GmbH"}, "x", "org: no note has the id or name 'Beta GmbH'"),
        ("new", {"name": "X", "org": "Hans Müller"}, "x", r"org: \[\[Hans Müller\]\] is a person, not an organization"),
        ("new", {"name": "X", "org": ["Acme AG"]}, "x", "org takes a single value"),
        ("new", ["name"], "x", "fields: an object"),
        ("Acme AG", {"name": "X"}, "x", r"match: \[\[Acme AG\]\] is an organization, not a person"),
        ("Nobody", {"name": "X"}, "x", "match: no note has the id or name 'Nobody'"),
    ],
)
def test_upsert_person_refuses(crm, match, given, reason, message):
    with pytest.raises(OrbitError, match=message):
        writes.upsert_person(crm, match, given, CHAT, reason)


@pytest.mark.parametrize("source", ["", None, "per_01M4WNN540CGMAHYXV1R90AA5X", "[[Nowhere]]"])
def test_a_source_is_required_and_must_exist_if_it_names_a_note(crm, source):
    with pytest.raises(OrbitError, match="source"):
        writes.upsert_person(crm, "new", {"name": "X"}, source, "x")


def test_a_file_as_source_is_the_interaction_logged_from_it(crm, tmp_path):
    # An agent may name the email's file rather than the interaction: the observation still links the interaction.
    original = tmp_path / "mail" / "2026-10-20 0800 Ausschreibung.md"
    logged = writes.log_interaction(
        crm, "email", "2026-10-20T08:00:00+02:00", subject="Tender", source_file=str(original)
    )
    spelled = str(original).replace("\\", "/").upper()  # another spelling of the same file
    writes.add_observation(crm, "Acme AG", "Plans a tender", "Ausschreibung", "high", spelled)
    assert f"- 2026-10-20 · Plans a tender · «Ausschreibung» · [[{logged['name']}]] · high" in text(
        crm, "02_Organizations/Acme AG.md"
    )


@pytest.mark.parametrize("path", ["D:\\mail\\2026\\x.md", "/home/tobias/mail/x.eml", "\\\\server\\mail\\x.eml"])
def test_a_file_no_interaction_was_logged_from_is_no_source(crm, path):
    with pytest.raises(OrbitError, match=r"source: .* is a file no interaction was logged from: log the interaction"):
        writes.add_observation(crm, "Acme AG", "x", "y", "high", path)


def test_a_new_person_records_why_and_from_where(crm, example):
    result = writes.upsert_person(
        crm, "new", {"name": "Lea Frei", "emails": ["lea@frei.example"]}, CHAT, "met at a fair"
    )
    assert result["created"] is True
    assert result["path"] == str(example / "01_People" / "Lea Frei.md")
    assert result["changed"] == [
        {"id": result["id"], "type": "person", "name": "Lea Frei", "path": result["path"], "action": "created"}
    ]
    assert text(crm, "01_People/Lea Frei.md").endswith(
        "review_status: confirmed\ncreated: 2026-10-22\nupdated: 2026-10-22\n---\n## Notes\n\n"
        "## History\n- 2026-10-22 · created: met at a fair · Tobias in chat, 2026-10-22\n"
    )


def test_a_name_taken_gets_a_distinguisher_and_keeps_the_plain_name_as_alias(crm):
    hans = ["Hans Müller"]  # another one: a Hans Müller there already is refused, as alike
    first = writes.upsert_person(
        crm, "new", {"name": "Hans Müller", "org": "Acme AG"}, CHAT, "a namesake", distinct_from=hans
    )
    assert first["name"] == "Hans Müller (Acme AG)"
    assert fields(crm, first["id"])["aliases"] == ["Hans Müller"]
    hans.append(first["id"])
    second = writes.upsert_person(
        crm, "new", {"name": "Hans Müller", "org": "Acme AG"}, CHAT, "another", distinct_from=hans
    )
    assert second["name"] == "Hans Müller (2)"
    anna = ["Anna Keller"]
    third = writes.upsert_person(
        crm, "new", {"name": "Anna Keller", "location": "Bern"}, CHAT, "a namesake", distinct_from=anna
    )
    assert third["name"] == "Anna Keller (Bern)"


def test_provisional_people_need_review(crm):
    result = writes.upsert_person(crm, "new", {"name": "Hansi"}, CHAT, "unsure", provisional=True)
    assert fields(crm, result["id"])["review_status"] == "needs_review"


def test_unsure_and_different_at_once_is_refused(crm):
    # An import created a second note for one person as provisional, to be asked about, and recorded it as another
    # person in the same call; the owner's answer that they are the same then couldn't merge them.
    with pytest.raises(OrbitError, match="provisional says it may be one of them, distinct_from that it is not"):
        writes.upsert_person(crm, "new", {"name": "Hans Müller"}, CHAT, "unsure", True, ["Hans Müller"])


def test_a_new_person_at_an_organization_s_domain_works_there(crm):
    # 19 people from a school's addresses floated without the school, which the vault knew by its domain.
    result = writes.upsert_person(crm, "new", {"name": "Lea Frei", "emails": ["lea.frei@acme-ag.example"]}, CHAT, "x")
    assert (fields(crm, result["id"])["org"], result["org_from_domain"]) == ("[[Acme AG]]", "[[Acme AG]]")
    student = writes.upsert_person(crm, "new", {"name": "Max Muster", "emails": ["max@students.acme-ag.example"]},
                                   CHAT, "x")  # fmt: skip
    assert fields(crm, student["id"])["org"] == "[[Acme AG]]"  # a subdomain is the organization's too


def test_an_org_from_the_domain_only_where_none_is_given(crm):
    crm.vault.write(
        "02_Organizations/Beta AG.md",
        "---\ntype: organization\nid: org_01M4WNN44RG8NK7BC7R54A18GE\nname: Beta AG\n---\n",
    )
    crm.refresh()
    given = writes.upsert_person(crm, "new", {"name": "Lea Frei", "emails": ["lea@acme-ag.example"], "org": "Beta AG"},
                                 CHAT, "x")  # fmt: skip
    assert (fields(crm, given["id"])["org"], "org_from_domain" in given) == ("[[Beta AG]]", False)
    private = writes.upsert_person(crm, "new", {"name": "Max Muster", "emails": ["max@gmail.com"]}, CHAT, "x")
    assert "org" not in fields(crm, private["id"])
    writes.upsert_person(crm, "Me", {"emails": ["tobias@acme-ag.example"]}, CHAT)
    assert "org" not in fields(crm, "Me")  # the owner's school or employer is theirs to say


def test_a_known_person_without_org_gets_it_from_a_new_address(crm):
    result = writes.upsert_person(crm, "Hans", {"emails": ["hans@acme-ag.example"]}, CHAT)
    assert (fields(crm, "Hans")["org"], result["filled"]) == ("[[Acme AG]]", ["org"])


def test_updating_a_person_merges_lists_fills_blanks_and_reports_conflicts(crm):
    result = writes.upsert_person(
        crm,
        "Hans Müller",
        {
            "emails": ["hans.mueller@acme-ag.example", "h.mueller@acme-ag.example"],
            "location": "Winterthur",
            "job_title": "Head of Procurement",
            "salutation": "du",
        },
        EMAIL,
    )
    assert (result["created"], result["filled"], result["added"]) == (
        False,
        ["location"],
        {"emails": ["h.mueller@acme-ag.example"]},
    )
    assert result["conflicts"] == [{"field": "job_title", "stored": "Leiter Einkauf", "given": "Head of Procurement"}]
    assert result["hint"] == "set_fields changes a stored value"
    page = text(crm, HANS)
    assert "  - h.mueller@acme-ag.example\n" in page
    assert "job_title: Leiter Einkauf\n" in page
    assert page.endswith(f"- 2026-10-14 · location: Winterthur · {EMAIL}\n")
    assert "updated: 2026-10-22" in page


def test_updating_with_what_is_known_changes_nothing(crm):
    before = text(crm, HANS)
    result = writes.upsert_person(crm, "per_01M4WNN540CGMAHYXV1R90AA5V", {"job_title": "leiter einkauf"}, CHAT)
    assert (result["changed"], result["conflicts"]) == ([], [])
    assert text(crm, HANS) == before


def test_colleagues_are_colleagues_both_ways(crm):
    writes.upsert_person(crm, "Hans", {"colleague_of": ["Anna Keller"]}, CHAT)
    assert fields(crm, "Anna Keller")["colleague_of"] == ["[[Hans Müller]]", "[[Hans]]"]


# upsert_organization and upsert_topic


@pytest.mark.parametrize(
    "match, given, message",
    [
        ("new", {"name": "Gmail", "domains": ["gmail.com"]}, "gmail.com is a free-mail domain"),
        (
            "new",
            {"name": "Acme Two", "domains": ["acme-ag.example"]},
            r"domains: acme-ag.example belongs to \[\[Acme AG\]\]",
        ),
        ("new", {"name": "X", "uid_che": "CHE-123.456.789"}, None),
    ],
)
def test_upsert_organization_refuses(crm, match, given, message):
    if message is None:  # a UID taken
        writes.upsert_organization(crm, "Acme AG", {"uid_che": "CHE-123.456.789"}, CHAT)
        message = r"uid_che: CHE-123.456.789 belongs to \[\[Acme AG\]\]"
    with pytest.raises(OrbitError, match=message):
        writes.upsert_organization(crm, match, given, CHAT, "x")


def test_an_organization_may_list_its_own_domain_again(crm):
    result = writes.upsert_organization(crm, "Acme AG", {"domains": ["acme-ag.example"], "industry": "Machines"}, CHAT)
    assert result["filled"] == ["industry"]


def test_a_new_topic_is_active_and_records_why_only_if_told(crm):
    result = writes.upsert_topic(crm, "new", {"name": "Messe 2027", "orgs": ["Acme AG"]}, CHAT)
    assert fields(crm, result["id"])["status"] == "active"
    assert "## History" not in text(crm, "05_Topics/Messe 2027.md")
    result = writes.upsert_topic(crm, "new", {"name": "Messe 2028"}, CHAT, "planned in chat")
    assert "- 2026-10-22 · created: planned in chat · Tobias in chat, 2026-10-22" in text(
        crm, "05_Topics/Messe 2028.md"
    )


# link_entities


@pytest.mark.parametrize(
    "a, relation, b, message",
    [
        (
            "Hans Müller",
            "parent",
            "Acme AG",
            r"relation: the relations of \[\[Hans Müller\]\], a person, are org, reports_to",
        ),
        ("Hans Müller", "org", "Anna Keller", r"to: \[\[Anna Keller\]\] is a person, not an organization"),
        ("Hans Müller", "colleague_of", "Hans Müller", "to: a note can't be linked to itself"),
        ("2026-10-18 Duplicate – Hans and Hans Müller", "candidates", "Hans", "a review, are none"),
        ("Inbox", "org", "Acme AG", r"relation: the relations of \[\[Inbox\]\], a note of no type, are none"),
    ],
)
def test_link_entities_refuses(crm, a, relation, b, message):
    crm.vault.write("Inbox.md", "A loose note.\n")
    crm.refresh({"Inbox.md"})
    with pytest.raises(OrbitError, match=message):
        writes.link_entities(crm, a, relation, b, CHAT)


def test_a_person_may_be_named_by_an_address(crm):
    writes.link_entities(crm, "Wartungsvertrag 2027", "people", " Hansi.Mueller@GMAIL.com ", CHAT)
    assert "[[Hans]]" in fields(crm, "Wartungsvertrag 2027")["people"]
    with pytest.raises(OrbitError, match=r"to: no person has the address nobody@x\.example"):
        writes.link_entities(crm, "Wartungsvertrag 2027", "people", "nobody@x.example", CHAT)


def test_a_role_address_names_no_person(crm):
    # An agent that linked one was told to create its person, which upsert_person then refuses.
    with pytest.raises(OrbitError, match=r"to: info@acme-ag\.example is a role address, which belongs to no person;"):
        writes.link_entities(crm, "2026-10-18 Email – Segelwochenende Bodensee", "cc", "info@acme-ag.example", CHAT)


def test_link_entities_sets_several_links_at_once(crm):
    links = [
        {"relation": "to", "to": "Anna Keller"},
        {"relation": "cc", "to": "hans.mueller@acme-ag.example"},
        {"relation": "topics", "to": "Wartungsvertrag 2027"},
    ]
    result = writes.link_entities(crm, "2026-10-18 Email – Segelwochenende Bodensee", source=CHAT, links=links)
    assert result["links"] == [
        {"relation": "to", "to": "[[Anna Keller]]", "linked": True},
        {"relation": "cc", "to": "[[Hans Müller]]", "linked": True},
        {"relation": "topics", "to": "[[Wartungsvertrag 2027]]", "linked": True},
    ]
    assert fields(crm, "Anna Keller")["last_contact"] == "2026-10-18"
    again = writes.link_entities(crm, "2026-10-18 Email – Segelwochenende Bodensee", source=CHAT, links=links)
    assert ([link["linked"] for link in again["links"]], again["changed"]) == ([False, False, False], [])


@pytest.mark.parametrize(
    "relation, to, links, message",
    [
        (None, None, None, "give relation and to, or links"),
        ("to", "Anna Keller", [{"relation": "cc", "to": "Hans"}], "give relation and to, or links"),
        (None, None, [{"relation": "to"}], r"links: each a \{\"relation\": …, \"to\": …\}"),
        (None, None, [{"relation": "to", "to": "Anna Keller"}, {"relation": "to", "to": "Nobody"}], "no note has"),
    ],
)
def test_link_entities_checks_every_link_before_it_writes_one(crm, relation, to, links, message):
    path = "03_Interactions/2026/2026-10/2026-10-18 Email – Segelwochenende Bodensee.md"
    before = text(crm, path)
    with pytest.raises(OrbitError, match=message):
        writes.link_entities(crm, path.rsplit("/", 1)[1][:-3], relation, to, CHAT, links=links)
    assert text(crm, path) == before


def test_log_interaction_links_the_people_whose_addresses_it_knows(crm):
    result = writes.log_interaction(
        crm,
        "email",
        "2026-10-20T08:00:00+02:00",
        subject="Kickoff",
        sender="Hans.Mueller@acme-ag.example",
        to=["tobias@meinefirma.example", "lea@frei.example"],
        cc=["info@acme-ag.example", "Anna Keller"],
    )
    logged = fields(crm, result["id"])
    assert (logged["from"], logged["to"], logged["cc"]) == ("[[Hans Müller]]", ["[[Me]]"], ["[[Anna Keller]]"])
    assert result["unknown_addresses"] == ["lea@frei.example"]
    assert result["role_addresses"] == ["info@acme-ag.example"]
    assert "resolve each with resolve_entity" in result["hint"]
    stranger = writes.log_interaction(
        crm, "email", "2026-10-20T09:00:00+02:00", subject="Hi", sender="lea@frei.example"
    )
    assert ("from" not in fields(crm, stranger["id"]), stranger["unknown_addresses"]) == (True, ["lea@frei.example"])


def test_log_interaction_lists_what_doesnt_exist_yet_and_logs_it_all_the_same(crm):
    # What an email is about is created with the email as its source, so the email comes first.
    result = writes.log_interaction(
        crm,
        "email",
        "2026-10-20T08:00:00+02:00",
        subject="Ausschreibung",
        sender="Lea Frei",
        to=["Me", "Marco Rossi"],
        orgs=["Acme AG", "Gamma AG"],
        topics=["Wartungsvertrag 2027", "Ausschreibung 2028"],
    )
    logged = fields(crm, result["id"])
    assert (logged["to"], logged["orgs"], logged["topics"], "from" in logged) == (
        ["[[Me]]"],
        ["[[Acme AG]]"],
        ["[[Wartungsvertrag 2027]]"],
        False,
    )
    assert (result["unknown_people"], result["unknown_orgs"], result["unknown_topics"]) == (
        ["Lea Frei", "Marco Rossi"],
        ["Gamma AG"],
        ["Ausschreibung 2028"],
    )
    assert "upsert_organization" in result["hint"]
    assert "unknown_addresses" not in result


def test_an_interaction_from_a_local_file_links_the_file(crm, tmp_path):
    original = tmp_path / "mail" / "2026-10-20 0800 Offerte.md"
    result = writes.log_interaction(
        crm, "email", "2026-10-20T08:00:00+02:00", subject="Offerte", source_file=str(original)
    )
    assert (
        Path(result["path"])
        .read_text(encoding="utf-8")
        .endswith(f"## Original\n- [2026-10-20 0800 Offerte.md]({original.as_uri()})\n")
    )
    relative = writes.log_interaction(crm, "email", "2026-10-21", subject="Other", source_file="mail/x.eml")
    assert "## Original" not in Path(relative["path"]).read_text(encoding="utf-8")  # relative to what, orbit can't tell
    program = writes.log_interaction(crm, "email", "2026-10-22", subject="Odd", source_file="C:\\Temp\\x.exe")
    assert "## Original" not in Path(program["path"]).read_text(encoding="utf-8")


def test_changing_a_persons_org_moves_the_old_one_to_former_orgs(crm):
    writes.upsert_organization(crm, "new", {"name": "Beta GmbH"}, CHAT, "a new employer")
    result = writes.link_entities(crm, "Hans Müller", "org", "Beta GmbH", "Tobias in chat, 2026-11-20")
    assert (result["to"], result["linked"]) == ("[[Beta GmbH]]", True)
    found = fields(crm, "Hans Müller")
    assert (found["org"], found["former_orgs"]) == ("[[Beta GmbH]]", ["[[Acme AG]]"])
    assert text(crm, HANS).endswith("- 2026-10-22 · org: [[Acme AG]] → [[Beta GmbH]] · Tobias in chat, 2026-11-20\n")
    writes.link_entities(crm, "Hans Müller", "org", "Acme AG", CHAT)
    found = fields(crm, "Hans Müller")
    assert (found["org"], found["former_orgs"]) == ("[[Acme AG]]", ["[[Beta GmbH]]"])


def test_an_org_the_same_source_takes_back_is_a_correction_not_a_former_org(crm):
    # An import set an org on a guess and took it back; former_orgs kept an employment no one had stated.
    writes.upsert_organization(crm, "new", {"name": "Beta GmbH"}, CHAT, "a new employer")
    said = "Tobias in chat, 2026-11-20"
    writes.link_entities(crm, "Hans Müller", "org", "Beta GmbH", said)  # a change: Acme AG was another source's
    writes.set_fields(crm, "Hans Müller", {"org": "Acme AG"}, said, "2026-11-20")  # the same source takes it back
    found = fields(crm, "Hans Müller")
    assert (found["org"], "former_orgs" in found) == ("[[Acme AG]]", False)
    writes.upsert_person(crm, "new", {"name": "Lea Frei", "org": "Beta GmbH"}, said, "named in the chat")
    writes.set_fields(crm, "Lea Frei", {"org": None}, said, "2026-11-20")  # set at creation by the same source
    assert "former_orgs" not in fields(crm, "Lea Frei")


def test_items_come_out_of_a_list_with_a_line_in_the_history(crm):
    writes.upsert_person(crm, "Hans Müller", {"emails": ["hans@old.example"]}, CHAT)
    result = writes.set_fields(crm, "Hans Müller", {}, CHAT, "2026-10-22", remove={"emails": ["Hans@Old.example"]})
    assert result["removed"] == [{"field": "emails", "item": "hans@old.example"}]
    assert "hans@old.example" not in fields(crm, "Hans Müller")["emails"]
    assert text(crm, HANS).endswith('- 2026-10-22 · emails: hans@old.example → "" · Tobias in chat, 2026-10-22\n')
    again = writes.set_fields(crm, "Hans Müller", {}, CHAT, "2026-10-22", remove={"emails": ["hans@old.example"]})
    assert (again["removed"], again["changed"]) == ([], [])  # gone already: nothing to do
    assert crm.index.holder("email", "hans@old.example") is None  # the index knows


def test_colleagues_come_apart_both_ways(crm):
    writes.link_entities(crm, "Hans", "colleague_of", "Anna Keller", CHAT)
    result = writes.set_fields(crm, "Hans", {}, CHAT, "2026-10-22", remove={"colleague_of": ["Anna Keller"]})
    assert [r["item"] for r in result["removed"]] == ["[[Anna Keller]]"]
    assert "[[Hans]]" not in fields(crm, "Anna Keller").get("colleague_of", [])
    assert len(result["changed"]) == 2
    writes.link_entities(crm, "Hans", "colleague_of", "Anna Keller", CHAT)
    anna = crm.vault.path("01_People/Anna Keller.md")  # a hand edit took Hans out of Anna's list already
    anna.write_text(anna.read_text(encoding="utf-8").replace('  - "[[Hans]]"\n', ""), "utf-8")
    crm.refresh()
    result = writes.set_fields(crm, "Hans", {}, CHAT, "2026-10-22", remove={"colleague_of": ["Anna Keller"]})
    assert len(result["changed"]) == 1


@pytest.mark.parametrize(
    "remove, message",
    [
        ({"job_title": ["x"]}, "remove: job_title isn't a list; clear it with changes"),
        ({"merged_from": ["x"]}, "remove: merged_from is orbit's to keep"),
        ({"emails": "x@y.example"}, r"remove: emails takes a list of items"),
        ({"colour": ["x"]}, "remove: colour isn't a field of a person"),
        (["emails"], "remove: an object of list fields and the items to take out"),
    ],
)
def test_what_can_t_come_out_of_a_list_is_named(crm, remove, message):
    with pytest.raises(OrbitError, match=message):
        writes.set_fields(crm, "Hans Müller", {}, CHAT, "2026-10-22", remove=remove)


def test_set_fields_needs_a_change_or_an_item_to_remove(crm):
    with pytest.raises(OrbitError, match="changes: an object of fields and their new values"):
        writes.set_fields(crm, "Hans Müller", {}, CHAT, "2026-10-22")


def test_linking_again_changes_nothing(crm):
    result = writes.link_entities(crm, "Hans Müller", "org", "Acme AG", CHAT)
    assert (result["linked"], result["changed"]) == (False, [])
    result = writes.link_entities(crm, "Wartungsvertrag 2027", "people", "Hans Müller", CHAT)
    assert (result["linked"], result["changed"]) == (False, [])


def test_people_linked_to_an_interaction_were_in_contact(crm):
    sailing = "2026-10-18 Email – Segelwochenende Bodensee"
    writes.link_entities(crm, sailing, "mentioned", "Anna Keller", CHAT)
    assert fields(crm, "Anna Keller")["last_contact"] == "2026-10-14"
    writes.link_entities(crm, sailing, "participants", "Anna Keller", CHAT)
    assert fields(crm, "Anna Keller")["last_contact"] == "2026-10-18"
    writes.link_entities(crm, sailing, "participants", "Me", CHAT)
    assert "last_contact" not in fields(crm, "Me")


@pytest.mark.parametrize("date", ["soon", "[]", "true", "\n  -\n  - 2026-10-18"])
def test_an_interaction_whose_date_a_hand_edit_broke_sets_no_last_contact(crm, date):
    sailing = "2026-10-18 Email – Segelwochenende Bodensee"
    note = crm.vault.path(f"03_Interactions/2026/2026-10/{sailing}.md")
    note.write_text(note.read_text(encoding="utf-8").replace("2026-10-18T19:02:00+02:00", date), "utf-8")
    crm.refresh()
    result = writes.link_entities(crm, sailing, "participants", "Anna Keller", CHAT)
    assert result["linked"] is True
    assert fields(crm, "Anna Keller")["last_contact"] == "2026-10-14"


def test_an_org_a_hand_edit_made_a_list_moves_to_former_orgs_item_by_item(crm):
    writes.upsert_organization(crm, "new", {"name": "Beta GmbH"}, CHAT, "a new employer")
    edit_hans = crm.vault.path(HANS)
    edit_hans.write_text(
        edit_hans.read_text(encoding="utf-8").replace('org: "[[Acme AG]]"', 'org:\n  - "[[Acme AG]]"\n  -'), "utf-8"
    )
    crm.refresh()
    writes.link_entities(crm, "Hans Müller", "org", "Beta GmbH", CHAT)
    found = fields(crm, "Hans Müller")
    assert (found["org"], found["former_orgs"]) == ("[[Beta GmbH]]", ["[[Acme AG]]"])


def test_linking_colleagues_links_both(crm):
    writes.link_entities(crm, "Hans", "colleague_of", "Anna Keller", CHAT)
    assert "[[Hans]]" in fields(crm, "Anna Keller")["colleague_of"]


# link_document


def test_link_document(crm):
    result = writes.link_document(crm, "Wartungsvertrag 2027", "C:\\Offers\\Offer (v2).pdf", "Offer [v2]", EMAIL)
    assert result["existing"] is False
    assert fields(crm, "Wartungsvertrag 2027")["documents"] == ["[Offer (v2)](<C:\\Offers\\Offer (v2).pdf>)"]
    assert text(crm, "05_Topics/Wartungsvertrag 2027.md").endswith(
        f"## Documents\n- [Offer (v2)](file:///C:/Offers/Offer%20%28v2%29.pdf) · {EMAIL}\n"
    )  # a link Obsidian opens the file with; the field keeps the path as given
    again = writes.link_document(crm, "Wartungsvertrag 2027", "C:\\Offers\\Offer (v2).pdf", "Other title", CHAT)
    assert (again["existing"], again["changed"]) == (True, [])
    writes.link_document(crm, EMAIL, "https://acme-ag.example/o.pdf", "Offer", EMAIL)
    assert "## Documents\n- [Offer](https://acme-ag.example/o.pdf)\n" in text(
        crm, "03_Interactions/2026/2026-10/2026-10-14 Email – AW Offerte Wartungsvertrag 2027.md"
    )


@pytest.mark.parametrize(
    "document, link",
    [
        ("/home/tobias/Offers/Offer v2.pdf", "file:///home/tobias/Offers/Offer%20v2.pdf"),
        ("D:\\Scans\\ID.JPG", "file:///D:/Scans/ID.JPG"),
        ("Offers/Offer.pdf", "Offers/Offer.pdf"),  # relative: to what, orbit can't tell
        ("doc-4711", "doc-4711"),
        # A click must neither run a program nor send the owner's Windows credentials to another computer, as a
        # file on a share does: an email can talk an agent into linking either.
        ("C:\\Tools\\setup.exe", "C:\\Tools\\setup.exe"),
        ("/home/tobias/run.sh", "/home/tobias/run.sh"),
        ("\\\\server\\share\\Offer.pdf", "\\\\server\\share\\Offer.pdf"),
    ],
)
def test_documents_that_are_local_files_are_linked_as_files(crm, document, link):
    writes.link_document(crm, "Wartungsvertrag 2027", document, "Offer", EMAIL)
    assert text(crm, "05_Topics/Wartungsvertrag 2027.md").endswith(f"## Documents\n- [Offer]({link}) · {EMAIL}\n")


def test_an_interactions_documents_are_linked_as_files_too(crm):
    attached = [{"title": "Offer", "document": "D:\\o.pdf"}]
    result = writes.log_interaction(crm, "email", "2026-10-20T08:00:00+02:00", subject="Offer", documents=attached)
    assert fields(crm, result["id"])["documents"] == ["[Offer](D:\\o.pdf)"]
    assert "## Documents\n- [Offer](file:///D:/o.pdf)\n" in Path(result["path"]).read_text(encoding="utf-8")


def test_link_document_passes_over_an_empty_item(crm):
    topic = crm.vault.path("05_Topics/Wartungsvertrag 2027.md")
    topic.write_text(topic.read_text(encoding="utf-8").replace("status:", "documents:\n  -\nstatus:"), "utf-8")
    crm.refresh()
    result = writes.link_document(crm, "Wartungsvertrag 2027", "https://x.example/o.pdf", "Offer", EMAIL)
    assert result["existing"] is False
    assert fields(crm, "Wartungsvertrag 2027")["documents"] == [None, "[Offer](https://x.example/o.pdf)"]


@pytest.mark.parametrize(
    "entity, document, title, message",
    [
        ("Send revised offer for Wartungsvertrag 2027", "x", "y", "is a task, not a person or an organization"),
        ("Acme AG", "", "Offer", "document and title"),
        ("Acme AG", "x", " ", "document and title"),
        ("Acme AG", "<x>", "Offer", "can't contain < or >"),
    ],
)
def test_link_document_refuses(crm, entity, document, title, message):
    with pytest.raises(OrbitError, match=message):
        writes.link_document(crm, entity, document, title, CHAT)


# add_observation and set_fields


def test_observations_are_dated_by_their_source_and_not_repeated(crm):
    result = writes.add_observation(crm, "Acme AG", "Has 200 staff", "rund 200 Mitarbeitende", "medium", EMAIL)
    assert result["existing"] is False
    line = f"- 2026-10-14 · Has 200 staff · «rund 200 Mitarbeitende» · {EMAIL} · medium"
    assert f"## Observations\n{line}\n\n## History" in text(crm, "02_Organizations/Acme AG.md")
    again = writes.add_observation(crm, "Acme AG", "Has 200 staff", "other words", "high", EMAIL)
    assert (again["existing"], again["changed"]) == (True, [])
    later = writes.add_observation(crm, "Acme AG", "Moved", "umgezogen", "high", CHAT, observed_at="2026-09-30")
    assert "- 2026-09-30 · Moved" in text(crm, "02_Organizations/Acme AG.md")
    assert later["existing"] is False


def test_the_same_evidence_again_is_the_same_observation(crm):
    # A reply sent twice, or a fact repeated in a reply's quoted history: the same words, another source.
    writes.add_observation(crm, "Acme AG", "Has 200 staff", "rund 200 Mitarbeitende", "medium", EMAIL)
    again = writes.add_observation(crm, "Acme AG", "Employs about 200", " Rund 200\nMitarbeitende", "high", CHAT)
    assert (again["existing"], again["changed"]) == (True, [])
    assert text(crm, "02_Organizations/Acme AG.md").count("200 Mitarbeitende") == 1
    other = writes.add_observation(crm, "Acme AG", "Is a large employer", "rund 200 Mitarbeitende", "medium", EMAIL)
    assert other["existing"] is False  # one source's words may state several facts


@pytest.mark.parametrize(
    "entity, statement, confidence, observed_at, message",
    [
        ("Acme AG", "x", "low", None, "confidence: high or medium"),
        ("Acme AG", " ", "high", None, "statement and evidence"),
        ("Acme AG", "x", "high", "soon", "observed_at: 'soon' is not a date"),
        (EMAIL, "x", "high", None, "is an interaction, not a person or an organization or a topic"),
    ],
)
def test_add_observation_refuses(crm, entity, statement, confidence, observed_at, message):
    with pytest.raises(OrbitError, match=message):
        writes.add_observation(crm, entity, statement, "words", confidence, CHAT, observed_at)


# retract_observation


def test_a_wrong_observation_is_retracted_and_kept_in_history(crm):
    # A review found a fact about someone else on a note; it could add facts, never take one back.
    writes.add_observation(crm, "Acme AG", "Has 200 staff", "rund 200 Mitarbeitende", "medium", EMAIL)
    writes.add_observation(crm, "Acme AG", "Moved", "umgezogen", "high", EMAIL)
    result = writes.retract_observation(crm, "Acme AG", " Has 200\nstaff ", "Example AG's staff, not Acme's", CHAT)
    assert (result["name"], result["retracted"], len(result["changed"])) == ("Acme AG", 1, 1)
    note = text(crm, "02_Organizations/Acme AG.md")
    observations, history = note.split("## History")
    assert "Has 200 staff" not in observations
    assert "- 2026-10-14 · Moved · «umgezogen»" in observations
    line = (f"- {crm.today()} · retracted: Has 200 staff ‹rund 200 Mitarbeitende› {EMAIL} → Example AG's staff, not "
            f"Acme's · {CHAT}")  # fmt: skip
    assert line in history
    assert [o["statement"] for o in reads.context(crm, "Acme AG")["observations"]] == ["Moved"]


def test_every_copy_of_a_wrong_statement_is_retracted(crm):
    writes.add_observation(crm, "Acme AG", "Has 200 staff", "rund 200 Mitarbeitende", "medium", EMAIL)
    writes.add_observation(crm, "Acme AG", "Has 200 staff", "200 Leute", "high", CHAT)
    assert writes.retract_observation(crm, "Acme AG", "Has 200 staff", "it has 20", CHAT)["retracted"] == 2


def test_retracting_what_no_observation_says_names_those_there_are(crm):
    writes.add_observation(crm, "Acme AG", "Moved", "umgezogen", "high", EMAIL)
    with pytest.raises(OrbitError) as error:
        writes.retract_observation(crm, "Acme AG", "Has 300 staff", "x", CHAT)
    assert str(error.value) == (
        "statement: no observation on Acme AG says 'Has 300 staff'; give one of its statements as "
        "get_entity_context shows it: 'Moved'"
    )


@pytest.mark.parametrize(
    "entity, statement, why, message",
    [
        ("Acme AG", " ", "x", "statement and why"),
        ("Acme AG", "x", "", "statement and why"),
        (EMAIL, "x", "y", "is an interaction, not a person or an organization or a topic"),
        ("Acme AG", "x", "y", "no observation on Acme AG says 'x'; it has none"),
    ],
)
def test_retract_observation_refuses(crm, entity, statement, why, message):
    with pytest.raises(OrbitError, match=message):
        writes.retract_observation(crm, entity, statement, why, CHAT)


def test_set_fields_writes_a_history_line_dated_when_observed(crm):
    result = writes.set_fields(
        crm, "Hans Müller", {"job_title": "Head of Procurement", "location": "Zürich"}, "Tobias in chat", "2026-11-20"
    )
    assert (result["applied"], result["not_applied"]) == (["job_title", "location"], [])
    page = text(crm, HANS)
    assert "- 2026-11-20 · job_title: Leiter Einkauf → Head of Procurement · Tobias in chat\n" in page
    assert "- 2026-11-20 · location: Zürich · Tobias in chat\n" in page


def test_set_fields_keeps_a_newer_value_and_notes_the_older_one(crm):
    writes.set_fields(crm, "Hans Müller", {"job_title": "Head of Procurement"}, CHAT, "2026-11-20")
    result = writes.set_fields(
        crm, "Hans Müller", {"job_title": "Einkäufer"}, EMAIL, "2026-10-01", evidence="Hans, Einkäufer"
    )
    assert result["applied"] == []
    assert result["not_applied"] == [
        {"field": "job_title", "value": "Einkäufer", "stored": "Head of Procurement", "stored_since": "2026-11-20"}
    ]
    assert (
        "- 2026-10-01 · job_title: Einkäufer; not applied, the stored value is from 2026-11-20 · «Hans, Einkäufer» · "
        f"{EMAIL} · medium" in text(crm, HANS)
    )


def test_a_clearing_not_applied_leaves_no_observation(crm):
    # That a source doesn't name a value is no fact about the note.
    writes.set_fields(crm, "Hans Müller", {"job_title": "Head of Procurement"}, CHAT, "2026-11-20")
    before = text(crm, HANS)
    result = writes.set_fields(crm, "Hans Müller", {"job_title": None}, EMAIL, "2026-10-01")
    assert result["not_applied"] == [
        {"field": "job_title", "value": None, "stored": "Head of Procurement", "stored_since": "2026-11-20"}
    ]
    assert (result["changed"], text(crm, HANS)) == ([], before)


def test_set_fields_against_the_creation_date(crm):
    result = writes.set_fields(crm, "Hans Müller", {"job_title": "Einkäufer"}, CHAT, "2026-10-01")
    assert result["not_applied"][0]["stored_since"] == "2026-10-14"  # the date of the email it was created from
    assert writes.set_fields(crm, "Hans Müller", {"location": "Bern"}, CHAT, "2026-10-01")["applied"] == ["location"]


def test_set_fields_clears_and_moves_orgs(crm):
    writes.upsert_organization(crm, "new", {"name": "Beta GmbH"}, CHAT, "x")
    result = writes.set_fields(crm, "Hans Müller", {"org": "Beta GmbH", "job_title": None}, CHAT, "2026-11-20")
    assert result["applied"] == ["org", "job_title"]
    found = fields(crm, "Hans Müller")
    assert (found["org"], found["former_orgs"], "job_title" in found) == ("[[Beta GmbH]]", ["[[Acme AG]]"], False)
    assert '- 2026-11-20 · job_title: Leiter Einkauf → "" · Tobias in chat, 2026-10-22\n' in text(crm, HANS)
    unchanged = writes.set_fields(crm, "Hans Müller", {"org": "Beta GmbH", "department": ""}, CHAT, "2026-11-21")
    assert (unchanged["applied"], unchanged["changed"]) == ([], [])


@pytest.mark.parametrize(
    "name, message",
    [
        ("id", "id: orbit sets it itself"),
        ("type", "type: orbit sets it itself"),
        ("me", "me: orbit sets it itself"),
        ("last_contact", "last_contact: orbit sets it itself"),
        ("created", "created: orbit sets it itself"),
        ("mood", "person has no field 'mood'"),
        ("name", "name: a person needs one; give the new one instead"),
    ],
)
def test_set_fields_clears_only_what_it_may_change(crm, name, message):
    before = text(crm, HANS)
    with pytest.raises(OrbitError, match=message):
        writes.set_fields(crm, "Hans Müller", {name: None}, CHAT, "2026-11-20")
    assert text(crm, HANS) == before


@pytest.mark.parametrize(
    "changes, observed_at, message",
    [
        ({"emails": ["x@y.example"]}, "2026-11-20", "emails is a list: add to it with upsert_person"),
        ({}, "2026-11-20", "changes: an object"),
        ({"job_title": "x"}, None, "observed_at: None is not a date"),
        ({"review_status": "maybe"}, "2026-11-20", "review_status: 'maybe' is not one of"),
    ],
)
def test_set_fields_refuses(crm, changes, observed_at, message):
    with pytest.raises(OrbitError, match=message):
        writes.set_fields(crm, "Hans Müller", changes, CHAT, observed_at)


# log_interaction


def test_log_interaction_is_idempotent_on_the_message_id(crm):
    result = writes.log_interaction(
        crm, "email", "2026-10-14T09:32:00+02:00", message_id=" <CAF3x9Q2kq7Lm@mail.gmail.com>"
    )
    assert (result["name"], result["existing"], result["changed"]) == (
        "2026-10-18 Email – Segelwochenende Bodensee",
        True,
        [],
    )


OFFER = "2026-10-14 Email – AW Offerte Wartungsvertrag 2027"
OFFER_ID = "<20261014093200.4711@acme-ag.example>"


def test_a_retry_learns_what_the_interaction_holds_already(crm):
    again = writes.log_interaction(crm, "email", "2026-10-14T09:32:00+02:00", message_id=OFFER_ID)
    assert again["recorded"] == {
        "from": "[[Hans Müller]]",
        "to": ["[[Me]]"],
        "cc": ["[[Anna Keller]]"],
        "orgs": ["[[Acme AG]]"],
        "topics": ["[[Wartungsvertrag 2027]]"],
        "summary": True,
        "decisions": 1,
        "key_quote": True,
        "tasks": [f"[[{SEND}]]", "[[Anna Keller to follow up on the technical clarification]]"],
        "documents": 0,
    }
    call = {"kind": "call", "date": "2026-10-20T08:15:00+02:00", "subject": "Rückruf"}
    writes.log_interaction(crm, **call)
    retried = writes.log_interaction(crm, **call)
    assert retried["recorded"] == {"summary": False, "decisions": 0, "key_quote": False, "tasks": [], "documents": 0}


def test_a_reply_links_the_email_it_answers_and_shows_its_thread(crm):
    reply = writes.log_interaction(
        crm, "email", "2026-10-15T10:00:00+02:00", subject="AW: AW: Offerte", sender="Anna Keller", in_reply_to=OFFER_ID
    )
    assert fields(crm, reply["id"])["replies_to"] == f"[[{OFFER}]]"
    thread = reply["thread"]
    assert [i["name"] for i in thread["interactions"]] == [OFFER, reply["name"]]
    assert thread["interactions"][0] | {"id": None} == {
        "id": None,
        "name": OFFER,
        "date": "2026-10-14T09:32:00+02:00",
        "kind": "email",
        "from": "[[Hans Müller]]",
        "subject": "AW: Offerte Wartungsvertrag 2027",
    }
    assert thread["topics"] == ["[[Wartungsvertrag 2027]]"]
    assert [(t["name"], t["status"]) for t in thread["open_tasks"]] == [
        ("Anna Keller to follow up on the technical clarification", "waiting"),
        ("Send revised offer for Wartungsvertrag 2027", "open"),
    ]


def test_a_reply_found_by_its_references_links_the_latest_one_known(crm):
    references = ["<20261010160500.0815@meinefirma.example>", OFFER_ID, "<unknown@x.example>"]
    reply = writes.log_interaction(
        crm, "email", "2026-10-16", subject="Re", in_reply_to="<gone@x>", references=references
    )
    assert fields(crm, reply["id"])["replies_to"] == f"[[{OFFER}]]"


def test_an_email_logged_after_its_reply_is_linked_from_it(crm):
    reply = writes.log_interaction(crm, "email", "2026-10-21", subject="Re: Plan", in_reply_to="<plan@acme-ag.example>")
    assert "replies_to" not in fields(crm, reply["id"])
    assert "thread" not in reply  # nothing else in its thread yet
    first = writes.log_interaction(crm, "email", "2026-10-20", subject="Plan", message_id="<plan@acme-ag.example>")
    assert fields(crm, reply["id"])["replies_to"] == f"[[{first['name']}]]"
    assert [c["name"] for c in first["changed"]] == [first["name"], reply["name"]]
    assert [i["name"] for i in first["thread"]["interactions"]] == [first["name"], reply["name"]]


def test_a_reply_that_cant_be_read_any_more_is_passed_over(crm):
    reply = writes.log_interaction(crm, "email", "2026-10-21", subject="Re", in_reply_to="<plan@acme-ag.example>")
    note = crm.vault.path(crm.find(reply["id"]).path)
    note.write_text("---\ntype: interaction\nkind: [email\n---\n", encoding="utf-8")  # broken since it was indexed
    first = writes.log_interaction(crm, "email", "2026-10-20", subject="Plan", message_id="<plan@acme-ag.example>")
    assert [c["name"] for c in first["changed"]] == [first["name"]]


def test_header_addresses_with_a_display_name(crm):
    result = writes.log_interaction(
        crm,
        "email",
        "2026-10-20",
        subject="Kickoff",
        sender='"Müller, Hans" <Hans.Mueller@acme-ag.example>',
        to=["Lea Frei <lea@frei.example>"],
    )
    assert fields(crm, result["id"])["from"] == "[[Hans Müller]]"
    assert result["unknown_addresses"] == ["lea@frei.example"]
    created = writes.upsert_person(
        crm, "new", {"name": "Lea Frei", "emails": ["Lea Frei <lea@frei.example>"]}, CHAT, "x"
    )
    assert fields(crm, created["id"])["emails"] == ["lea@frei.example"]
    assert crm.find("Lea <LEA@frei.example>").name == "Lea Frei"


def test_an_email_that_names_itself_as_answered_answers_nothing(crm):
    odd = writes.log_interaction(crm, "email", "2026-10-21", subject="Odd", message_id="<a@x>", in_reply_to="<a@x>")
    assert "replies_to" not in fields(crm, odd["id"])


def test_replies_to_is_orbits_to_set(crm):
    with pytest.raises(OrbitError, match="replies_to: orbit sets it itself"):
        writes._fields(crm, "interaction", {"replies_to": OFFER})


def test_replies_with_a_long_subject_on_one_day_get_numbers(crm):
    subject = "AW: WG: " + " ".join(["Offerte Wartungsvertrag 2027 mit Pikettdienst am Wochenende"] * 3)
    first, second = (
        writes.log_interaction(crm, "email", f"2026-10-20T{time}:00+02:00", subject=subject, sender="Anna Keller")
        for time in ("08:15", "09:40")
    )
    assert len(first["name"]) <= 120
    assert second["name"] == f"{first['name']} (2)"
    again = writes.log_interaction(crm, "email", "2026-10-20T09:40:00+02:00", subject=subject, sender="Anna Keller")
    assert again["id"] == second["id"]  # a retry finds it under its number


def test_a_call_without_subject_is_named_after_whom_it_was_with(crm):
    result = writes.log_interaction(
        crm,
        "call",
        "2026-10-20T08:15:00+02:00",
        sender="Anna Keller",
        documents=[{"title": "Notes", "document": "n.txt"}],
    )
    assert result["name"] == "2026-10-20 Call – Anna Keller"
    assert fields(crm, "Anna Keller")["last_contact"] == "2026-10-20"
    assert fields(crm, result["id"])["documents"] == ["[Notes](n.txt)"]
    note = writes.log_interaction(crm, "note", "2026-10-21")
    assert note["name"] == "2026-10-21 Note"
    assert note["path"].endswith(
        "03_Interactions/2026/2026-10/2026-10-21 Note.md".replace("/", "\\" if "\\" in note["path"] else "/")
    )


def test_an_older_interaction_leaves_last_contact_alone(crm):
    writes.log_interaction(crm, "meeting", "2026-09-01", participants=["Hans Müller", "Me"])
    assert fields(crm, "Hans Müller")["last_contact"] == "2026-10-14"


def test_a_reply_joins_the_thread_of_the_email_it_answers(crm):
    reply = writes.log_interaction(
        crm,
        "email",
        "2026-10-15T10:00:00+02:00",
        subject="AW: AW: Offerte",
        in_reply_to="<20261014093200.4711@acme-ag.example>",
    )
    assert fields(crm, reply["id"])["thread"] == "<20261010160500.0815@meinefirma.example>"
    unknown = writes.log_interaction(crm, "email", "2026-10-15T11:00:00+02:00", subject="x", in_reply_to="<a@b>")
    assert fields(crm, unknown["id"])["thread"] == "<a@b>"
    sailing = writes.log_interaction(
        crm, "email", "2026-10-19", subject="Re", in_reply_to="<CAF3x9Q2kq7Lm@mail.gmail.com>"
    )
    assert fields(crm, sailing["id"])["thread"] == "<CAF3x9Q2kq7Lm@mail.gmail.com>"


@pytest.mark.parametrize(
    "arguments, message",
    [
        ({"kind": "email", "date": "2026-10-14T09:32:00"}, "needs its UTC offset"),
        ({"kind": "fax", "date": "2026-10-14"}, "kind: 'fax' is not one of"),
        ({"kind": None, "date": "2026-10-14"}, "kind: required"),
        ({"kind": "email", "date": "2026-10-14", "orgs": ["Hans Müller"]}, "is a person, not an organization"),
        ({"kind": "email", "date": "2026-10-14", "sender": "Acme AG"}, "is an organization, not a person"),
        ({"kind": "email", "date": "2026-10-14", "topics": [""]}, "topics: give an id"),
    ],
)
def test_log_interaction_refuses(crm, arguments, message):
    with pytest.raises(OrbitError, match=message):
        writes.log_interaction(crm, **arguments)


# Tasks


def test_create_task_is_idempotent_and_lists_itself_on_its_interaction(crm):
    again = writes.create_task(crm, "Send revised offer for Wartungsvertrag 2027", "Me", EMAIL)
    assert (again["existing"], again["changed"]) == (True, [])
    result = writes.create_task(crm, "Call Hans back", "Me", EMAIL, related=["Hans Müller"])
    assert [c["name"] for c in result["changed"]] == [
        "Call Hans back",
        "2026-10-14 Email – AW Offerte Wartungsvertrag 2027",
    ]
    assert "- [[Call Hans back]]\n\n## Key quote" in text(
        crm, "03_Interactions/2026/2026-10/2026-10-14 Email – AW Offerte Wartungsvertrag 2027.md"
    )
    assert text(crm, "04_Tasks/Call Hans back.md").endswith("---\n## Details\n\n## Notes\n")


def test_a_task_from_a_topic_lists_itself_nowhere(crm):
    result = writes.create_task(crm, "Plan kickoff", "Me", "Wartungsvertrag 2027", details="line one\nline two")
    assert len(result["changed"]) == 1
    assert "## Details\n> line one\n> line two\n" in text(crm, "04_Tasks/Plan kickoff.md")


@pytest.mark.parametrize(
    "title, owner, origin, message",
    [
        (" ", "Me", EMAIL, "title: what is to be done"),
        ("x", "Me", None, "origin: the interaction the task comes from"),
        ("x", None, EMAIL, "owner: who is to do it"),
        ("x", "Wartungsvertrag 2027", EMAIL, "is a topic, not a person or an organization"),
    ],
)
def test_create_task_refuses(crm, title, owner, origin, message):
    with pytest.raises(OrbitError, match=message):
        writes.create_task(crm, title, owner, origin)


def test_an_email_lists_the_open_tasks_of_whom_it_is_with(crm):
    # A later email often settles a task in another thread (the refund came, the answer arrived): agents never
    # closed one, since they saw only the open tasks of the email's own thread.
    result = writes.log_interaction(crm, "email", "2026-10-21T08:00:00+02:00", subject="Klärung erledigt",
                                    sender="anna.keller@acme-ag.example", to=["Me"])  # fmt: skip
    assert [(t["name"], t["status"]) for t in result["open_tasks"]] == [
        ("Anna Keller to follow up on the technical clarification", "waiting")]  # fmt: skip
    with_acme = writes.log_interaction(crm, "email", "2026-10-21T09:00:00+02:00", subject="Hallo", to=["Me"],
                                       orgs=["Acme AG"])  # fmt: skip
    assert len(with_acme["open_tasks"]) == 2
    alone = writes.log_interaction(crm, "note", "2026-10-21", subject="Gedanken", participants=["Me"])
    assert "open_tasks" not in alone  # the owner's own tasks aren't listed for every note they are in


def test_an_email_lists_a_bounded_number_of_open_tasks(crm, monkeypatch):
    # An organization with many open tasks would fill the agent's context with every email it is in.
    monkeypatch.setattr(writes, "OPEN_TASKS", 1)
    result = writes.log_interaction(crm, "email", "2026-10-21T09:00:00+02:00", subject="Hallo", to=["Me"],
                                    orgs=["Acme AG"])  # fmt: skip
    assert (len(result["open_tasks"]), result["open_tasks_more"]) == (1, 1)


def test_an_organization_can_owe_the_owner_a_task(crm):
    # A shop's refund or a provider's fix is the company's to do, not one person's: agents were refused 25 times.
    result = writes.create_task(crm, "Refund the cancelled order", "Acme AG", EMAIL, status="waiting")
    assert fields(crm, result["id"])["owner"] == "[[Acme AG]]"


SEND = "Send revised offer for Wartungsvertrag 2027"


def test_a_task_like_an_open_one_of_the_same_thread_is_refused_until_told(crm):
    reply = writes.log_interaction(crm, "email", "2026-10-16", subject="Re", in_reply_to=OFFER_ID)
    with pytest.raises(OrbitError) as refused:
        writes.create_task(crm, "Send the revised offer by 1 November", "Me", reply["id"])
    assert str(refused.value) == (
        f"similar open tasks: [[{SEND}]] (tsk_01M4WNN72GCA5MKPBDSQMQMGRD). If this is one of them, call create_task "
        'with its id as match, or update_task it; if it is another task, call create_task again with match "new".'
    )
    same = writes.create_task(crm, "Send the revised offer by 1 November", "Me", reply["id"], match=SEND)
    assert (same["name"], same["existing"], same["changed"]) == (SEND, True, [])
    new = writes.create_task(crm, "Send the revised offer by 1 November", "Me", reply["id"], match=" New ")
    assert (new["name"], new["existing"]) == ("Send the revised offer by 1 November", False)


def test_a_task_like_an_open_one_of_the_same_owner_and_matter_is_refused(crm):
    with pytest.raises(OrbitError, match=rf"similar open tasks: \[\[{SEND}\]\]"):
        writes.create_task(crm, "Send offer Wartungsvertrag 2027", "Me", "Wartungsvertrag 2027", related=["Acme AG"])


def test_a_task_like_one_elsewhere_or_done_is_new(crm):
    sailing = "2026-10-18 Email – Segelwochenende Bodensee"
    assert writes.create_task(crm, "Send revised offer for the boat", "Me", sailing)["existing"] is False
    writes.update_task(crm, SEND, CHAT, status="done")
    reply = writes.log_interaction(crm, "email", "2026-10-16", subject="Re", in_reply_to=OFFER_ID)
    assert writes.create_task(crm, "Send the revised offer by 1 November", "Me", reply["id"])["existing"] is False


def test_match_names_a_task(crm):
    with pytest.raises(OrbitError, match=r"match: \[\[Hans Müller\]\] is a person, not a task"):
        writes.create_task(crm, "x", "Me", EMAIL, match="Hans Müller")


def test_update_task_appends_what_changed_to_its_details(crm):
    task = "Anna Keller to follow up on the technical clarification"
    result = writes.update_task(crm, task, CHAT, status="done", note="She called on Monday.")
    assert result["updated"] is True
    page = text(crm, f"04_Tasks/{task}.md")
    assert "status: done\n" in page
    assert (
        "- 2026-10-22 · status: waiting → done; She called on Monday. · Tobias in chat, 2026-10-22\n\n## Notes" in page
    )
    assert writes.update_task(crm, task, CHAT, status="done")["updated"] is False
    writes.update_task(crm, task, EMAIL, due_note="sofort")
    assert "- 2026-10-14 · due_note: nächste Woche → sofort · " in text(crm, f"04_Tasks/{task}.md")


def test_update_task_refuses(crm):
    with pytest.raises(OrbitError, match="give what changed"):
        writes.update_task(crm, "Anna Keller to follow up on the technical clarification", CHAT)
    with pytest.raises(OrbitError, match="is a person, not a task"):
        writes.update_task(crm, "Hans Müller", CHAT, status="done")


def test_a_person_without_an_org_gets_one_without_former_orgs(crm):
    writes.link_entities(crm, "Hans", "org", "Acme AG", CHAT)
    found = fields(crm, "Hans")
    assert (found["org"], "former_orgs" in found) == ("[[Acme AG]]", False)


def test_a_task_already_listed_on_its_interaction_is_not_listed_twice(crm):
    path = "03_Interactions/2026/2026-10/2026-10-14 Email – AW Offerte Wartungsvertrag 2027.md"
    note = crm.vault.path(path)
    note.write_text(
        note.read_text(encoding="utf-8").replace("## Key quote", "- [[Call Hans]]\n\n## Key quote"), "utf-8"
    )
    result = writes.create_task(crm, "Call Hans", "Me", EMAIL)
    assert [c["name"] for c in result["changed"]] == ["Call Hans"]
    assert text(crm, path).count("[[Call Hans]]") == 1


def test_a_retried_new_person_returns_the_one_created(crm):
    first = writes.upsert_person(crm, "new", {"name": "Lea Frei"}, CHAT, "met at a fair")
    again = writes.upsert_person(crm, "new", {"name": "Lea Frei"}, CHAT, "met at a fair")
    assert (again["id"], again["created"], again["changed"]) == (first["id"], False, [])
    assert not crm.vault.path("01_People/Lea Frei (2).md").exists()
    namesake = writes.upsert_person(
        crm, "new", {"name": "Lea Frei"}, CHAT, "another Lea, from the club", distinct_from=[first["id"]]
    )
    assert (namesake["created"], namesake["name"]) == (True, "Lea Frei (2)")


def test_a_retried_interaction_without_message_id_returns_the_one_logged(crm):
    call = {"kind": "call", "date": "2026-10-20T08:15:00+02:00", "subject": "Rückruf", "sender": "Anna Keller"}
    first = writes.log_interaction(crm, **call)
    again = writes.log_interaction(crm, **call)
    assert (again["id"], again["existing"], again["changed"]) == (first["id"], True, [])
    later = writes.log_interaction(crm, **(call | {"date": "2026-10-20T16:00:00+02:00"}))
    assert (later["existing"], later["name"]) == (False, "2026-10-20 Call – Rückruf (2)")


def test_a_new_topic_named_like_an_existing_one_is_that_one(crm):
    again = writes.upsert_topic(crm, "new", {"name": "wartungsvertrag 2027", "orgs": ["Acme AG"]}, CHAT)
    assert (again["id"], again["created"]) == ("top_01M4WNN9104FB139QPZ3HYZ1VN", False)
    assert not crm.vault.path("05_Topics/wartungsvertrag 2027 (2).md").exists()


def test_new_is_new_in_any_case(crm):
    result = writes.upsert_person(crm, " New ", {"name": "Lea Frei"}, CHAT, "met at a fair")
    assert result["created"] is True


def test_a_summary_cant_break_the_notes_sections(crm):
    summary = "First line.\n## Notes\n```\nunclosed fence\n  # not a heading here either"
    result = writes.log_interaction(crm, "note", "2026-10-21", subject="Sections", summary=summary, key_quote="## q")
    page = crm.load(crm.find(result["id"]).path)
    assert page.body.headings() == ["Summary", "Key quote"]
    assert page.body.lines("Summary") == [
        "First line.",
        r"\## Notes",
        r"\```",
        "unclosed fence",
        r"  \# not a heading here either",
    ]
    writes.create_task(crm, "Follow up on the sections", "Me", result["id"])
    assert crm.load(crm.find(result["id"]).path).body.lines("Action items") == ["- [[Follow up on the sections]]"]
