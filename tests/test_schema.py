"""The note types: their fields and order, the problems a note's front matter can have, and cleaning given values."""

import re
from pathlib import Path

import pytest

from orbit import frontmatter, schema
from orbit.schema import SchemaError

from .conftest import EXAMPLE

NOTES = sorted(p for p in EXAMPLE.rglob("*.md") if "99_System" not in p.parts)


@pytest.mark.parametrize("path", NOTES, ids=lambda p: p.name)
def test_example_notes_keep_the_schema_in_its_order(path):
    fields, _ = frontmatter.read(path.read_text(encoding="utf-8"))
    assert schema.problems(fields) == []
    assert schema.unknown(fields["type"], fields) == []
    assert list(schema.order(fields["type"], fields)) == list(fields)
    assert path.relative_to(EXAMPLE).parts[0] == schema.TYPES[fields["type"]].folder


def test_every_type_has_its_own_prefix_and_folder():
    assert len({t.prefix for t in schema.TYPES.values()}) == len({t.folder for t in schema.TYPES.values()}) == 6
    assert schema.PREFIXES["per"] == "person"


def test_order_puts_unknown_fields_last():
    fields = {"mood": "good", "name": "Hans", "id": "x", "type": "person"}
    assert list(schema.order("person", fields)) == ["type", "id", "name", "mood"]
    assert schema.unknown("person", fields) == ["mood"]


def person(**fields):
    return {"type": "person", "id": "per_01M3V0RPR04X2CSM8CEMSVTWVA", "name": "Hans"} | fields


@pytest.mark.parametrize(
    "fields, found",
    [
        (
            {"type": "meeting"},
            [("type", "unknown type 'meeting'; one of person, organization, interaction, task, topic, review")],
        ),
        ({}, [("type", "no type")]),
        (person(id="org_01M3V0RPR04X2CSM8CEMSVTWVA"), [("id", "no valid id: per_ and a ULID")]),
        (person(id=None), [("id", "no id")]),
        (person(name=""), [("name", "missing")]),
        (person(emails="a@x.example"), [("emails", "should be a list")]),
        (person(org=["[[Acme AG]]"]), [("org", "should be a single value")]),
        (person(context="work"), [("context", "'work' is not one of professional, personal, both")]),
        (person(last_contact="14.10.2026"), [("last_contact", "'14.10.2026' is not a date (YYYY-MM-DD)")]),
        (person(last_contact="2026-02-30"), [("last_contact", "'2026-02-30' is not a date (YYYY-MM-DD)")]),
        (person(org="Acme AG"), [("org", "'Acme AG' is not a wikilink, e.g. \"[[Acme AG]]\"")]),
        (person(emails=["not-an-address"]), [("emails", "'not-an-address' is not an email address")]),
        (person(me="yes"), [("me", "should be true or false")]),
        (person(job_title=True), [("job_title", "should be text")]),
        (person(merged_from=["Hans"]), [("merged_from", "'Hans' is not an id")]),
        (person(emails=[None, "a@x.example"], phones=None), []),
    ],
)
def test_problems(fields, found):
    assert schema.problems(fields) == found


def test_problems_of_other_kinds():
    org = {"type": "organization", "id": "org_01M3V0RPR04X2CSM8CEMSVTWVA", "name": "Acme"}
    assert schema.problems(org | {"domains": ["acme"], "uid_che": "CHE-1"}) == [
        ("domains", "'acme' is not a domain"),
        ("uid_che", "'CHE-1' is not a Swiss company UID (CHE-123.456.789)"),
    ]
    interaction = {"type": "interaction", "id": "int_01M3V0RPR04X2CSM8CEMSVTWVA", "kind": "email"}
    assert schema.problems(interaction | {"date": "2026-10-14T09:32:00"}) == [
        ("date", "'2026-10-14T09:32:00' is not a date or an ISO 8601 time with offset")
    ]
    assert schema.problems(interaction | {"date": "soon"})[0][0] == "date"
    assert schema.problems(interaction | {"date": "2026-10-14", "sha256": "abc"}) == [
        ("sha256", "'abc' is not a SHA-256 hash in hex")
    ]
    assert schema.problems(interaction | {"date": "2026-10-14", "documents": ["offer.pdf"]}) == [
        ("documents", "'offer.pdf' is not a document as \"[title](reference)\"")
    ]


@pytest.mark.parametrize(
    "type_name, name, value, cleaned",
    [
        ("person", "name", "  Hans   Müller ", "Hans Müller"),
        ("person", "name", "   ", None),
        ("person", "name", None, None),
        ("person", "emails", " Hans@Acme.Example ", ["hans@acme.example"]),
        ("person", "emails", ["a@x.example", "A@x.example", ""], ["a@x.example"]),
        ("person", "emails", [], None),
        ("person", "salutation", "sie", "Sie"),
        ("person", "me", True, True),
        ("person", "org", "[[Acme AG]]", "[[Acme AG]]"),
        ("organization", "domains", ["https://www.Acme.example/"], ["acme.example"]),
        ("organization", "uid_che", "CHE123456789", "CHE-123.456.789"),
        ("organization", "uid_che", "che-123.456.789", "CHE-123.456.789"),
        ("interaction", "date", "2026-10-14T09:32+02:00", "2026-10-14T09:32:00+02:00"),
        ("interaction", "date", "2026-10-14T07:32:00Z", "2026-10-14T07:32:00+00:00"),
        ("interaction", "date", "2026-10-14", "2026-10-14"),
        ("interaction", "sha256", "AB" * 32, "ab" * 32),
        ("interaction", "documents", "[Offer](https://x.example/o.pdf)", ["[Offer](https://x.example/o.pdf)"]),
        ("interaction", "documents", "[Offer](<C:\\My Files\\o.pdf>)", ["[Offer](<C:\\My Files\\o.pdf>)"]),
    ],
)
def test_clean(type_name, name, value, cleaned):
    assert schema.clean(type_name, name, value) == cleaned


@pytest.mark.parametrize(
    "type_name, name, value, message",
    [
        ("person", "mood", "good", "person has no field 'mood'; its fields are name, aliases, emails"),
        ("person", "org", ["[[A]]"], "org takes a single value, not a list"),
        ("person", "me", "yes", "me takes true or false"),
        ("person", "name", 3, "name takes text, not int"),
        ("person", "emails", "nobody", "emails: 'nobody' is not an email address"),
        ("person", "context", "work", "context: 'work' is not one of"),
        ("person", "org", "Acme AG", "is not a wikilink"),
        ("interaction", "date", "2026-10-14T09:32", "date: '2026-10-14T09:32' needs its UTC offset"),
        ("interaction", "date", "next week", "is not a date or an ISO 8601 time"),
    ],
)
def test_clean_refuses(type_name, name, value, message):
    with pytest.raises(SchemaError, match=message.replace("(", r"\(").replace(")", r"\)")):
        schema.clean(type_name, name, value)


def test_links():
    assert schema.link("Acme AG") == "[[Acme AG]]"
    assert schema.link_target("[[Acme AG]]") == "Acme AG"
    assert schema.link_target("[[Hans Müller|Hans]]") == "Hans Müller"
    assert schema.link_target("[[Wartungsvertrag 2027#Notes]]") == "Wartungsvertrag 2027"
    assert schema.link_target("Acme AG") is None
    assert schema.link_target(None) is None


def test_the_format_reference_lists_every_field():
    docs = (Path(__file__).parents[1] / "docs" / "vault-format.md").read_text(encoding="utf-8")
    rows = {
        line.split("|")[1].strip(): line for line in docs.splitlines() if line.startswith("| ") and "`type`" in line
    }
    for name, spec in schema.TYPES.items():
        listed = re.findall(r"`(\w+)`", rows[name])
        assert listed == list(spec.names), name
        for field in spec.fields:
            if field.choices:
                assert f"`{field.name}` ({', '.join(field.choices)})" in rows[name], field.name
