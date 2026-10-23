"""Reviews: one question for the owner each, and the decisions they set in Obsidian, applied."""

import json

import pytest

from orbit import reads, reviews, upkeep
from orbit.errors import OrbitError

SAILING = "[[2026-10-18 Email – Segelwochenende Bodensee]]"
REVIEW = "90_Review/2026-10-18 Duplicate – Hans and Hans Müller.md"


def decide(crm, decision, path=REVIEW):
    note = crm.vault.path(path)
    note.write_text(note.read_text(encoding="utf-8").replace("decision: pending", f"decision: {decision}"), "utf-8")
    return crm.refresh({path})


def fields(crm, ref):
    return reads.context(crm, ref)["fields"]


def test_deciding_different_records_it_on_both_notes(crm):
    decide(crm, "different")
    hans, mueller = fields(crm, "Hans"), fields(crm, "Hans Müller")
    assert hans["distinct_from"] == ["[[Hans Müller]]"]
    assert mueller["distinct_from"] == ["[[Hans]]"]
    assert hans["review_status"] == "confirmed"
    history = crm.vault.path("01_People/Hans.md").read_text(encoding="utf-8")
    assert history.endswith(
        "- 2026-10-22 · review_status: needs_review → confirmed · [[2026-10-18 Duplicate – Hans and Hans Müller]]\n"
    )


def test_a_decision_is_applied_once(crm):
    decide(crm, "different")
    before = crm.vault.path("01_People/Hans Müller.md").read_text(encoding="utf-8")
    assert upkeep.apply_reviews(crm) == []
    crm.refresh()
    assert crm.vault.path("01_People/Hans Müller.md").read_text(encoding="utf-8") == before


def test_a_pending_decision_changes_nothing(crm):
    assert upkeep.apply_reviews(crm) == []
    assert "distinct_from" not in fields(crm, "Hans")


def test_deciding_same_merges_the_two(crm):  # in detail: test_upkeep.py
    decide(crm, "same")
    assert fields(crm, "Hans Müller")["merged_from"] == ["per_01M57ZJKJ8HWCPYDPQSTB9FCH9"]


def test_a_duplicate_answered_yes_is_merged(crm):
    # Agents ask "Is Hans the same person as Hans Müller?", and owners answer such questions with yes or no.
    decide(crm, "yes")
    assert fields(crm, "Hans Müller")["merged_from"] == ["per_01M57ZJKJ8HWCPYDPQSTB9FCH9"]


def test_a_duplicate_answered_no_is_recorded_as_different(crm):
    decide(crm, "no")
    assert fields(crm, "Hans")["distinct_from"] == ["[[Hans Müller]]"]


def test_a_review_whose_candidate_is_gone_is_left_alone(crm):
    crm.vault.path("01_People/Hans.md").unlink()
    decide(crm, "different")
    assert "distinct_from" not in fields(crm, "Hans Müller")


def test_reviews_of_other_kinds_are_answers_only(crm, example):
    result = reviews.propose(
        crm, "job_change", "Has Anna Keller left Acme AG?", ["Anna Keller"], ["Her mail bounced"], [], "Tobias in chat"
    )
    assert result["name"] == "2026-10-22 Job change – Anna Keller"
    path = f"90_Review/{result['name']}.md"
    assert (
        crm.vault.path(path)
        .read_text(encoding="utf-8")
        .endswith(
            "## Evidence for\n- Her mail bounced\n\n## Evidence against\n\n"
            "## How to answer\nSet `decision` to `yes` or `no`.\n"
        )
    )
    decide(crm, "yes", path)
    assert "distinct_from" not in fields(crm, "Anna Keller")


def test_proposing_again_returns_the_pending_review(crm):
    result = reviews.propose(crm, "duplicate", "Same?", ["Hans Müller", "Hans"], [], [], SAILING)
    assert (result["name"], result["existing"]) == ("2026-10-18 Duplicate – Hans and Hans Müller", True)
    decide(crm, "different")
    fresh = reviews.propose(crm, "duplicate", "Same after all?", ["Hans Müller", "Hans"], [], [], "Tobias in chat")
    assert (fresh["name"], fresh["existing"]) == ("2026-10-22 Duplicate – Hans Müller and Hans", False)


def test_a_pending_review_is_found_however_its_candidates_are_written(crm):
    note = crm.vault.path(REVIEW)
    note.write_text(note.read_text(encoding="utf-8").replace('"[[Hans Müller]]"', '"[[hans müller]]"'), "utf-8")
    crm.refresh()
    result = reviews.propose(crm, "duplicate", "Same?", ["Hans Müller", "Hans"], [], [], SAILING)
    assert (result["name"], result["existing"]) == ("2026-10-18 Duplicate – Hans and Hans Müller", True)


def test_a_review_of_several_names_them_all(crm):
    result = reviews.propose(crm, "other", "Do these three work together?", ["Hans", "Anna Keller", "Me"], [], [], "x")
    assert result["name"] == "2026-10-22 Question – Hans, Anna Keller and Me"


def test_duplicate_organizations(crm):
    crm.vault.write(
        "02_Organizations/ACME.md", "---\ntype: organization\nid: org_01M4WNN44RG8NK7BC7R54A18GB\nname: ACME\n---\n"
    )
    crm.refresh()
    result = reviews.propose(crm, "duplicate", "Same company?", ["ACME", "Acme AG"], [], [], "x")
    assert "records them as different organizations" in crm.vault.path(f"90_Review/{result['name']}.md").read_text(
        "utf-8"
    )
    decide(crm, "different", f"90_Review/{result['name']}.md")
    assert fields(crm, "Acme AG")["distinct_from"] == ["[[ACME]]"]


def test_a_hand_made_duplicate_review_of_mixed_types_is_left_alone(crm):
    crm.vault.write(
        "90_Review/Odd.md",
        "---\ntype: review\nid: rev_01M57ZJMHGT7KNNJKNG5AEW8A8\nkind: duplicate\nquestion: x\ncandidates:\n"
        '  - "[[Hans]]"\n  - "[[Acme AG]]"\ndecision: different\n---\n',
    )
    crm.refresh({"90_Review/Odd.md"})
    assert "distinct_from" not in fields(crm, "Hans")


@pytest.mark.parametrize(
    "kind, question, candidates, message",
    [
        ("merge", "x", ["Hans"], "kind: one of duplicate, job_change, address, other"),
        ("other", " ", ["Hans"], "question: the one question"),
        ("other", "x", [], "candidates: the notes the question is about"),
        ("duplicate", "x", ["Hans"], "a duplicate review asks about two people, two organizations or two topics"),
        ("duplicate", "x", ["Hans", "Acme AG"], "a duplicate review asks about two people"),
        ("duplicate", "x", ["Wartungsvertrag 2027", "Acme AG"], "a duplicate review asks about two people"),
        ("duplicate", "x", ["Wartungsvertrag 2027", "Send revised offer for Wartungsvertrag 2027"], "two people"),
    ],
)
def test_propose_refuses(crm, kind, question, candidates, message):
    with pytest.raises(OrbitError, match=message):
        reviews.propose(crm, kind, question, candidates, [], [], "x")


def test_evidence_keeps_to_one_line_each(crm):
    result = reviews.propose(crm, "other", "Same team?", "Hans", ["one\n## Notes", "  "], [], "x")
    page = crm.load(crm.find(result["id"]).path)
    assert page.body.headings() == ["Evidence for", "Evidence against", "How to answer"]
    assert page.body.lines("Evidence for") == ["- one ## Notes"]


def test_two_topics_can_be_asked_about_and_merged(crm):
    crm.vault.write(
        "05_Topics/Wartung.md", "---\ntype: topic\nid: top_01M4WNN44RG8NK7BC7R54A18GC\nname: Wartung\n---\n"
    )
    crm.refresh()
    result = reviews.propose(crm, "duplicate", "Same topic?", ["Wartung", "Wartungsvertrag 2027"], [], [], "x")
    assert "records them as different topics" in crm.vault.path(f"90_Review/{result['name']}.md").read_text("utf-8")
    decide(crm, "same", f"90_Review/{result['name']}.md")
    left = [n for n in ("Wartung", "Wartungsvertrag 2027") if crm.vault.path(f"05_Topics/{n}.md").exists()]
    assert len(left) == 1  # merged into the older


def ask_open(crm, question="Is Example Bank your bank?", about=("Me",)):
    result = reviews.propose(crm, "question", question, list(about), ["Bank account opened, 2014-10-09"], [], SAILING)
    return f"90_Review/{result['name']}.md"


def answer(crm, path, text):
    """Type the answer into the question's `answer` property, as the Review base's table does."""
    note = crm.vault.path(path)
    note.write_text(note.read_text(encoding="utf-8").replace('answer: ""', f"answer: {json.dumps(text)}"), "utf-8")
    return crm.refresh({path})


def test_an_open_question_is_answered_in_the_owner_s_words(crm):
    # The owner knows what no email says (their bank, who a teacher was), and answers in the Review base's table,
    # which edits a note's properties, not its body.
    path = ask_open(crm)
    name = path.removeprefix("90_Review/").removesuffix(".md")
    text = crm.vault.path(path).read_text(encoding="utf-8")
    assert path.startswith("90_Review/2026-10-18 Open question – Me")
    assert "Write your answer in its `answer` property, in your own words" in text
    assert 'answer: ""' in text  # a cell to type into
    assert "## Answer" not in text
    assert fields(crm, name)["decision"] == "pending"
    answer(crm, path, "Yes, I have an account there since 2014.")
    found = reads.context(crm, name)
    assert found["fields"]["decision"] == "answered"  # orbit sees the answer: no field to set by hand
    assert found["fields"]["answer"] == "Yes, I have an account there since 2014."
    answered = reads.list_entities(crm, "review", {"kind": "question", "decision": "answered"})
    assert [r["name"] for r in answered["results"]] == [name]


def test_an_answer_acted_on_is_settled_once_with_what_was_done(crm):
    path = ask_open(crm)
    name = path.removeprefix("90_Review/").removesuffix(".md")
    with pytest.raises(OrbitError, match="not answered yet"):
        reviews.settle(crm, name, "Recorded the account on Me", "glean review, 2026-10-23")
    answer(crm, path, "yes")
    result = reviews.settle(crm, name, "Recorded the account on Me", "glean review, 2026-10-23")
    assert (result["existing"], fields(crm, name)["applied"]) == (False, "2026-10-22")
    text = crm.vault.path(path).read_text(encoding="utf-8")
    assert text.endswith("## Applied\n- 2026-10-22 · Recorded the account on Me · glean review, 2026-10-23\n")
    again = reviews.settle(crm, name, "Recorded it again", "glean review, 2026-10-24")
    assert (again["existing"], again["changed"]) == (True, [])  # settled already: nothing done twice
    with pytest.raises(OrbitError, match="done: what was done with the answer"):
        reviews.settle(crm, name, " ", "x")


def test_a_yes_no_answer_can_be_settled_too(crm):
    result = reviews.propose(crm, "other", "Did Hans move to Zurich?", ["Hans"], [], [], SAILING)
    path = f"90_Review/{result['name']}.md"
    decide(crm, "yes", path)
    assert reviews.settle(crm, result["name"], "Set Hans's location", "x")["existing"] is False


def test_only_reviews_are_settled(crm):
    with pytest.raises(OrbitError, match="review: Hans is a person, not a review"):
        reviews.settle(crm, "Hans", "x", "y")


def test_an_answer_left_empty_is_no_answer(crm):
    path = ask_open(crm)
    answer(crm, path, "   ")
    assert fields(crm, path.removeprefix("90_Review/").removesuffix(".md"))["decision"] == "pending"


def ask_address(crm, address="tobias@alt.example", who="Me"):
    question = f"Is {address} an address of {who}?"
    result = reviews.propose(crm, "address", question, [who], ["signs as Tobias"], [], SAILING, address=address)
    return f"90_Review/{result['name']}.md"


def test_an_address_answered_yes_is_added_once(crm):
    # Agents asked whether an address was the owner's; the answer yes did nothing, and they asked again.
    path = ask_address(crm)
    assert ask_address(crm) == path  # asked again while pending: the same review
    assert "orbit then adds tobias@alt.example to the emails of [[Me]]" in crm.vault.path(path).read_text("utf-8")
    decide(crm, "yes", path)
    assert "tobias@alt.example" in fields(crm, "Me")["emails"]
    assert fields(crm, path.removeprefix("90_Review/").removesuffix(".md"))["applied"] == "2026-10-22"


def test_an_address_answered_no_is_left_out(crm):
    decide(crm, "no", ask_address(crm))
    assert "tobias@alt.example" not in fields(crm, "Me")["emails"]


def test_an_address_someone_else_has_is_reported(crm):
    path = ask_address(crm, "anna.keller@acme-ag.example")
    decide(crm, "yes", path)
    assert "anna.keller@acme-ag.example belongs to [[Anna Keller]]" in crm.review_problems[path]


@pytest.mark.parametrize(
    "candidates, address, message",
    [
        (["Me"], None, "address: the address the question is about"),
        (["Me", "Anna Keller"], "x@y.example", "an address review asks about one person"),
        (["Acme AG"], "x@y.example", "an address review asks about one person"),
        (["Me"], "tobias@meinefirma.example", "tobias@meinefirma.example is one of \\[\\[Me\\]\\]'s already"),
        (["Me"], "info@acme-ag.example", "info@acme-ag.example is a role address"),
    ],
)
def test_an_address_review_needs_a_person_and_an_address(crm, candidates, address, message):
    with pytest.raises(OrbitError, match=message):
        reviews.propose(crm, "address", "Is it theirs?", candidates, [], [], "x", address=address)


def test_a_job_change_answered_yes_moves_the_person_once(crm):
    crm.vault.write(
        "02_Organizations/Beta AG.md",
        "---\ntype: organization\nid: org_01M4WNN44RG8NK7BC7R54A18GE\nname: Beta AG\n---\n",
    )
    crm.refresh()
    result = reviews.propose(
        crm, "job_change", "Does Hans work at Beta AG now?", ["Hans Müller", "Beta AG"], [], [], "x"
    )
    path = f"90_Review/{result['name']}.md"
    decide(crm, "yes", path)
    hans = fields(crm, "Hans Müller")
    assert (hans["org"], hans["former_orgs"]) == ("[[Beta AG]]", ["[[Acme AG]]"])
    note = crm.vault.path("01_People/Hans Müller.md")
    note.write_text(note.read_text("utf-8").replace('org: "[[Beta AG]]"', 'org: "[[Acme AG]]"'), "utf-8")
    crm.refresh()  # the owner changed it back by hand: an applied answer isn't applied again
    assert fields(crm, "Hans Müller")["org"] == "[[Acme AG]]"


def test_answered_reviews_show_in_a_notes_context(crm):
    # So that an agent sees what the owner said, and doesn't ask again.
    decide(crm, "no", ask_address(crm))
    (answered,) = reads.context(crm, "Me")["answered_reviews"]
    assert (answered["kind"], answered["decision"]) == ("address", "no")
    assert reads.context(crm, "Me")["pending_reviews"] == []


@pytest.mark.parametrize(
    "candidates, address, problem",
    [
        ('  - "[[Me]]"\n  - "[[Anna Keller]]"\n', "x@y.example", "an address review names one person, and the address"),
        ('  - "[[Me]]"\n', "info@y.example", "info@y.example is a role address"),
    ],
)
def test_a_hand_made_address_review_that_cant_be_applied_is_reported(crm, candidates, address, problem):
    crm.vault.write(
        "90_Review/Odd.md",
        "---\ntype: review\nid: rev_01M57ZJMHGT7KNNJKNG5AEW8A9\nkind: address\nquestion: x\ncandidates:\n"
        f"{candidates}address: {address}\ndecision: yes\n---\n",
    )
    crm.refresh({"90_Review/Odd.md"})
    assert problem in crm.review_problems["90_Review/Odd.md"]


def test_a_job_change_to_where_one_works_or_from_nowhere(crm):
    stays = reviews.propose(crm, "job_change", "Still at Acme?", ["Anna Keller", "Acme AG"], [], [], "x")
    decide(crm, "yes", f"90_Review/{stays['name']}.md")
    assert "former_orgs" not in fields(crm, "Anna Keller")
    joins = reviews.propose(crm, "job_change", "Does Hans work at Acme?", ["Hans", "Acme AG"], [], [], "x")
    decide(crm, "yes", f"90_Review/{joins['name']}.md")
    assert (fields(crm, "Hans")["org"], "former_orgs" in fields(crm, "Hans")) == ("[[Acme AG]]", False)
