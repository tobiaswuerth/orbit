"""resolve_entity: candidates with scores and the evidence for each; the caller decides."""

import pytest

from orbit.errors import OrbitError
from orbit.resolve import resolve

HANS = "Hans Müller"


def names_of(result):
    return [c["name"] for c in result["candidates"]]


@pytest.mark.parametrize("written", ["Hans Mueller", "Müller, Hans", "H. Müller", "hans müller", "Dr. Hans Müller"])
def test_finds_hans_mueller_however_his_name_is_written(crm, written):
    result = resolve(crm, "person", [written])
    assert names_of(result)[0] == HANS
    assert result["candidates"][0]["score"] >= 0.7


def test_finds_hansi_writing_from_his_company_domain(crm):
    result = resolve(crm, "person", ["Hansi"], ["h.m@acme-ag.example"])
    best = result["candidates"][0]
    assert best["name"] == HANS
    assert "nickname (name): Hansi" in best["reasons"]
    assert "same company domain acme-ag.example" in best["reasons"]
    assert "Hans" in names_of(result)  # the provisional Hans, who has Hansi as an alias


def test_a_candidate_carries_what_the_caller_needs_to_decide(crm, example):
    (best,) = [c for c in resolve(crm, "person", ["Hans Müller"])["candidates"] if c["name"] == HANS]
    assert best == {
        "id": "per_01M4WNN540CGMAHYXV1R90AA5V",
        "name": HANS,
        "path": str(example / "01_People" / "Hans Müller.md"),
        "score": 0.85,
        "reasons": ["same name (name): Hans Müller"],
        "org": "[[Acme AG]]",
        "job_title": "Leiter Einkauf",
        "emails": ["hans.mueller@acme-ag.example"],
        "last_contact": "2026-10-14",
        "review_status": "confirmed",
    }


def test_an_exact_address_is_the_person(crm):
    best = resolve(crm, "person", emails=["Hans.Mueller@acme-ag.example"])["candidates"][0]
    assert (best["name"], best["score"], best["reasons"][0]) == (
        HANS,
        1.0,
        "same email address hans.mueller@acme-ag.example",
    )


def test_an_address_as_a_header_writes_it(crm):
    best = resolve(crm, "person", emails=['"Müller, Hans" <Hans.Mueller@acme-ag.example>'])["candidates"][0]
    assert (best["name"], best["score"]) == (HANS, 1.0)


def test_tobias_own_addresses_return_me(crm):
    (me,) = resolve(crm, "person", emails=["tobias.privat@mail.example"])["candidates"]
    assert (me["name"], me["me"], me["score"]) == ("Me", True, 1.0)


def test_role_addresses_never_map_to_a_person(crm):
    result = resolve(crm, "person", ["Info"], ["info@acme-ag.example"])
    assert result["notes"][0] == "info@acme-ag.example: role addresses belong to no person, so they were not looked for"


def test_free_mail_domains_say_nothing_about_an_employer(crm):
    result = resolve(crm, "person", ["Anna"], ["anna@gmail.com"])
    assert "gmail.com: free-mail domains say nothing about an employer" in result["notes"]
    assert all("company domain" not in r for c in result["candidates"] for r in c["reasons"])


def test_a_name_in_the_address(crm):
    result = resolve(crm, "person", emails=["hans.mueller@gmail.com"])
    best = result["candidates"][0]
    assert best["name"] == HANS
    assert best["reasons"] == ["same name (name) in the address hans.mueller@gmail.com"]
    assert best["score"] == 0.5


def test_names_that_sound_alike_are_candidates(crm):
    best = resolve(crm, "person", ["Hans Möller"])["candidates"][0]
    assert (best["name"], best["score"], best["reasons"]) == (HANS, 0.5, ["sounds alike (name): Hans Möller"])
    weak = resolve(crm, "person", ["Möller"])["candidates"][0]
    assert (weak["name"], weak["score"]) == (HANS, 0.25)
    assert resolve(crm, "person", ["Thomas Möller"])["candidates"] == []


def test_part_of_a_name(crm):
    result = resolve(crm, "person", ["Anna"])
    assert result["candidates"][0]["reasons"] == ["part of the name (name): Anna"]


def test_initials_that_dont_fit(crm):
    assert resolve(crm, "person", ["X. Müller"])["candidates"] == []
    result = resolve(crm, "person", ["H."])
    assert result["candidates"] == []
    assert result["notes"] == ['no candidate: if this is a new person, create it with match "new"']


def test_phone_org_and_job_title(crm):
    best = resolve(crm, "person", ["Hans"], phone="052 123 45 67", org="ACME", job_title="leiter einkauf")
    assert best["candidates"][0]["name"] == HANS
    assert best["candidates"][0]["reasons"] == [
        "same phone number",
        "part of the name (name): Hans",
        "works at Acme AG",
        "same job title",
    ]
    assert best["candidates"][0]["score"] == 0.95


def test_pairs_marked_different_come_back_flagged(crm):
    hans = crm.vault.path("01_People/Hans.md")
    hans.write_text(
        hans.read_text(encoding="utf-8").replace(
            "review_status", 'distinct_from:\n  - "[[Hans Müller]]"\nreview_status'
        ),
        encoding="utf-8",
    )
    crm.refresh()
    flagged = {c["name"]: c.get("distinct_from") for c in resolve(crm, "person", ["Hans"])["candidates"]}
    assert flagged["Hans"] == ["[[Hans Müller]]"]


def test_limit(crm):
    assert len(resolve(crm, "person", ["Hans"], limit=1)["candidates"]) == 1


@pytest.mark.parametrize(
    "query, reason, score",
    [
        ({"names_": ["ACME Aktiengesellschaft"]}, "same name without legal form (name): ACME Aktiengesellschaft", 0.85),
        ({"names_": ["acme ag"]}, "same name (name): acme ag", 0.9),
        ({"domain": "https://www.acme-ag.example/"}, "same domain acme-ag.example", 0.95),
        ({"emails": ["info@acme-ag.example"]}, "same domain acme-ag.example", 0.95),
        ({"emails": ["max@students.acme-ag.example"]}, "a subdomain of acme-ag.example", 0.9),
        ({"domain": "mail.zh.acme-ag.example"}, "a subdomain of acme-ag.example", 0.9),
    ],
)
def test_organizations(crm, query, reason, score):
    best = resolve(crm, "organization", **query)["candidates"][0]
    assert (best["name"], best["reasons"], best["score"]) == ("Acme AG", [reason], score)
    assert best["domains"] == ["acme-ag.example"]


def test_organizations_by_uid_and_part_of_the_name(crm):
    acme = crm.vault.path("02_Organizations/Acme AG.md")
    acme.write_text(
        acme.read_text(encoding="utf-8").replace("location:", "uid_che: CHE-123.456.789\nlocation:"), "utf-8"
    )
    crm.refresh()
    for written in ("che-123.456.789", "CHE123456789", "CHE-123.456.789 MWST"):
        best = resolve(crm, "organization", uid_che=written)["candidates"][0]
        assert (best["score"], best["reasons"]) == (1.0, ["same company UID CHE-123.456.789"]), written
    crm.vault.write("02_Organizations/Acme Holding AG.md", "---\ntype: organization\nname: Acme Holding AG\n---\n")
    crm.refresh()
    result = resolve(crm, "organization", ["Acme"])
    assert names_of(result) == ["Acme AG", "Acme Holding AG"]
    assert result["candidates"][1]["reasons"] == ["one name starts with the other (name): Acme"]


def test_topics(crm):
    result = resolve(crm, "topic", ["Wartungsvertrag"])
    assert result["candidates"][0]["reasons"] == ["most words alike (name): Wartungsvertrag"]  # one of two
    assert result["candidates"][0]["score"] == 0.7
    assert resolve(crm, "topic", ["Wartungsvertrag Pikett 2028"])["candidates"] == []  # one of four
    exact = resolve(crm, "topic", ["wartungsvertrag 2027"])["candidates"][0]
    assert (exact["score"], exact["status"]) == (0.9, "active")


def test_names_that_dont_match_add_nothing(crm):
    assert resolve(crm, "person", ["Dr.", "Zeta Omega"], domain="acme-ag.example")["candidates"] == []
    assert resolve(crm, "organization", ["Zeta"], domain="acme-ag.example")["candidates"][0]["reasons"] == [
        "same domain acme-ag.example"
    ]
    topic = crm.vault.path("05_Topics/Wartungsvertrag 2027.md")
    topic.write_text(topic.read_text(encoding="utf-8").replace("status:", "aliases:\n  - Pikett\nstatus:"), "utf-8")
    crm.refresh()
    assert resolve(crm, "topic", ["Wartungsvertrag"])["candidates"][0]["reasons"] == [
        "most words alike (name): Wartungsvertrag"
    ]


def test_empty_items_a_hand_edit_left_are_passed_over(crm):
    # A list item left empty in Obsidian reads as nothing; it mustn't break resolving for every query that finds it.
    for path, old, new in [
        ("01_People/Hans.md", "  - Hansi\n", "  - Hansi\n  -\n"),
        ("02_Organizations/Acme AG.md", "  - acme-ag.example\n", "  - acme-ag.example\n  -\naliases:\n  -\n"),
        ("05_Topics/Wartungsvertrag 2027.md", "status:", "aliases:\n  -\nstatus:"),
    ]:
        note = crm.vault.path(path)
        note.write_text(note.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    crm.refresh()
    assert names_of(resolve(crm, "person", ["Hansi"], ["h.m@acme-ag.example"]))[:2] == [HANS, "Hans"]
    assert names_of(resolve(crm, "organization", ["Acme"])) == ["Acme AG"]
    assert names_of(resolve(crm, "topic", ["Wartungsvertrag"])) == ["Wartungsvertrag 2027"]


def test_only_notes_of_the_type_asked_for(crm):
    assert resolve(crm, "organization", ["Hans Müller"])["candidates"] == []


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"type": "task", "names_": ["x"]}, "type: one of person, organization, topic"),
        ({"type": "person"}, "give at least one of names, emails"),
        ({"type": "person", "emails": ["nobody"]}, "emails: 'nobody' is not an email address"),
    ],
)
def test_errors_say_what_to_give(crm, kwargs, message):
    with pytest.raises(OrbitError, match=message):
        resolve(crm, **kwargs)


def test_a_name_inside_another_scores_low(crm):
    # Not the first words, and less than half of them: a candidate to show, never one to refuse a new note for.
    crm.vault.write("02_Organizations/Acme Holding AG.md", "---\ntype: organization\nname: Acme Holding AG\n---\n")
    crm.vault.write("05_Topics/Pikett.md", "---\ntype: topic\nname: Pikett Wartung Service Winter\n---\n")
    crm.refresh()
    holding = resolve(crm, "organization", ["Holding"])["candidates"][0]
    assert (holding["score"], holding["reasons"]) == (0.4, ["part of the name (name): Holding"])
    pikett = resolve(crm, "topic", ["Pikett"])["candidates"][0]
    assert (pikett["score"], pikett["reasons"]) == (0.4, ["part of the name (name): Pikett"])
