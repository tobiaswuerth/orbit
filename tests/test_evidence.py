"""Evidence checked against its source: a quote must be in the file its interaction was logged from, as written, where
orbit can read that file; parts that aren't together are joined with …. Agents shortened quotes, fixed their typos or
put words of their own in, and the vault kept them as the source's."""

import pytest

from orbit import writes
from orbit.errors import OrbitError

EMAIL = "Grüezi Herr Würth\n\nDas Budget für 2027 ist **freigegeben**. Wir starten im Januar.\n\nFreundliche Grüsse\n"


@pytest.fixture
def logged(crm, tmp_path):
    """An interaction logged from a Markdown file, and its id."""
    path = tmp_path / "email.md"
    path.write_text(EMAIL, encoding="utf-8")
    call = {"kind": "email", "date": "2026-10-20T08:15:00+02:00", "sender": "Anna Keller", "subject": "Budget"}
    return writes.log_interaction(crm, **call, source_file=str(path))["id"], path


def observe(crm, source, evidence, statement="Approved the 2027 budget"):
    return writes.add_observation(crm, "Acme AG", statement, evidence, "high", source)


@pytest.mark.parametrize(
    "evidence",
    [
        "Das Budget für 2027 ist freigegeben.",
        '"das budget für 2027 ist  freigegeben"',  # quotes, case and spaces aside; ** too
        "Das Budget für 2027 … Wir starten im Januar.",
        "Grüezi Herr Würth ... Freundliche Grüsse",
    ],
)
def test_a_quote_in_the_source_is_taken(crm, logged, evidence):
    assert observe(crm, logged[0], evidence)["existing"] is False


def test_a_quote_not_in_the_source_says_from_where(crm, logged):
    with pytest.raises(
        OrbitError, match=r"evidence: from «2027 ist freigegeben» on, it isn't in \[\[.+\]\] as written"
    ):
        observe(crm, logged[0], "Das Budget 2027 ist freigegeben")


def test_a_quote_from_an_email_s_quoted_history_is_taken_across_its_markers(crm, tmp_path):
    # A reply quotes the email it answers line by line with "> "; a quote over two such lines was refused.
    path = tmp_path / "reply.md"
    path.write_text(
        "Wie ging es?\n\n> offiziell darf ich keine Auskunft geben. Ich schlage vor, dass ich es \n"
        "> ihnen an der Abschlussfeier sage...\n>> > und noch\n>>  älter\n",
        encoding="utf-8",
    )
    call = {"kind": "email", "date": "2017-06-30T10:49:00+02:00", "sender": "Markus", "subject": "Re: ABU"}
    source = writes.log_interaction(crm, **call, source_file=str(path))["id"]
    assert observe(crm, source, "Ich schlage vor, dass ich es ihnen an der Abschlussfeier sage")["existing"] is False
    assert observe(crm, source, "und noch älter", "Older")["existing"] is False


def test_set_fields_evidence_is_checked_too(crm, logged):
    with pytest.raises(OrbitError, match="evidence: from «Head of Sales» on"):
        writes.set_fields(crm, "Anna Keller", {"job_title": "Head of Sales"}, logged[0], "2026-10-20", "Head of Sales")


def test_a_source_orbit_cant_read_isnt_checked(crm, logged, tmp_path):
    # A chat, a file gone, or an email with a PDF attached, which the quote may come from.
    assert observe(crm, "Tobias in chat, 2026-10-22", "words of no file")["existing"] is False
    logged[1].unlink()
    assert observe(crm, logged[0], "words of a file gone")["existing"] is False
    logged[1].write_text(EMAIL, encoding="utf-8")
    (tmp_path / "offer.pdf").write_bytes(b"%PDF")
    writes.link_document(crm, logged[0], str(tmp_path / "offer.pdf"), "Offer", "Tobias in chat, 2026-10-22")
    assert observe(crm, logged[0], "Preis: CHF 12'000", "Offered for CHF 12'000")["existing"] is False


def test_a_text_document_of_the_interaction_counts(crm, logged, tmp_path):
    (tmp_path / "notes.md").write_text("Preis: CHF 12'000 pro Jahr\n", encoding="utf-8")
    (tmp_path / "gone.md").write_text("x", encoding="utf-8")
    for name in ("notes.md", "gone.md"):
        writes.link_document(crm, logged[0], str(tmp_path / name), name, "Tobias in chat, 2026-10-22")
    (tmp_path / "gone.md").unlink()
    assert observe(crm, logged[0], "Preis: CHF 12'000 pro Jahr")["existing"] is False
    with pytest.raises(OrbitError, match="evidence"):
        observe(crm, logged[0], "Preis: CHF 13'000 pro Jahr")
