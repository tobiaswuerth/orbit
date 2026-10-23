"""Notes a hand edit left in shapes the schema doesn't allow: an empty list item, a list where one value belongs or one
value where a list does, a boolean, nothing. lint_vault reports them; no tool may fail on them other than with an
error that says what to do."""

import contextlib
import shutil

import pytest

from orbit import frontmatter, lint, reads, reviews, schema, upkeep, writes
from orbit.crm import Crm
from orbit.errors import OrbitError
from orbit.resolve import resolve

from .conftest import EXAMPLE, NOW

EMAIL = "[[2026-10-14 Email – AW Offerte Wartungsvertrag 2027]]"
CHAT = "Tobias in chat, 2026-10-22"
HANS, TASK = "Hans Müller", "Send revised offer for Wartungsvertrag 2027"
OFFER_ID = "<20261014093200.4711@acme-ag.example>"
NOTES = {
    "person": "01_People/Hans Müller.md",
    "organization": "02_Organizations/Acme AG.md",
    "interaction": "03_Interactions/2026/2026-10/2026-10-14 Email – AW Offerte Wartungsvertrag 2027.md",
    "task": "04_Tasks/Send revised offer for Wartungsvertrag 2027.md",
    "topic": "05_Topics/Wartungsvertrag 2027.md",
    "review": "90_Review/2026-10-18 Duplicate – Hans and Hans Müller.md",
}
SHAPES = {
    "an empty item": lambda field, value: [None, *(value if isinstance(value, list) else [value] if value else [])],
    "the other shape": lambda field, value: (value[0] if value else "x") if field.many else [value or "x", "y"],
    "a boolean": lambda field, value: True,
    "nothing": lambda field, value: None,
}
CALLS = [  # reads first, and what renames or merges notes last, so that each call still finds the notes it names
    lambda c: resolve(c, "person", ["Hans Müller", "H. Mueller"], ["hans.mueller@acme-ag.example"], org="Acme"),
    lambda c: resolve(c, "organization", ["Acme AG"], domain="acme-ag.example", uid_che="CHE-123.456.789"),
    lambda c: resolve(c, "topic", ["Wartungsvertrag 2027"]),
    lambda c: reads.search(c, "Mueller"),
    *(lambda c, n=name: reads.context(c, n.rsplit("/", 1)[1].removesuffix(".md")) for name in NOTES.values()),
    *(lambda c, t=kind: reads.list_entities(c, t, sort="-created") for kind in NOTES),
    lambda c: reads.list_entities(c, "task", {"due": {"<": "2027-01-01"}, "related": "Acme AG"}, sort="due"),
    lambda c: lint.lint(c),
    lambda c: upkeep.create_missing_references(c, dry_run=True),
    lambda c: writes.upsert_person(c, HANS, {"aliases": ["HM"], "job_title": "CEO", "colleague_of": ["Hans"]}, CHAT),
    lambda c: writes.upsert_person(c, "new", {"name": "Lea", "org": "Acme AG", "colleague_of": [HANS]}, CHAT, "x"),
    lambda c: writes.upsert_organization(c, "Acme AG", {"aliases": ["ACME"], "domains": ["acme.example"]}, CHAT),
    lambda c: writes.upsert_topic(c, "new", {"name": "Wartungsvertrag 2027", "people": ["Hans"]}, CHAT),
    lambda c: writes.link_entities(c, HANS, "org", "Acme AG", CHAT),
    lambda c: writes.link_entities(c, EMAIL, "to", "Hans", CHAT),
    lambda c: writes.link_entities(c, TASK, "related", "Hans", CHAT),
    lambda c: writes.link_document(c, "Acme AG", "https://x.example", "X", CHAT),
    lambda c: writes.add_observation(c, "Wartungsvertrag 2027", "Big", "gross", "high", EMAIL),
    lambda c: writes.set_fields(c, HANS, {"job_title": "CEO", "location": None, "org": "Acme AG"}, CHAT, "2026-11-01"),
    lambda c: writes.log_interaction(c, "email", "2026-10-20", subject="Hi", sender=HANS, orgs=["Acme AG"]),
    lambda c: writes.log_interaction(c, "email", "2026-10-14T09:32:00+02:00", subject="AW: Offerte"),
    lambda c: writes.log_interaction(
        c, "email", "2026-10-21", in_reply_to=OFFER_ID, to=["anna.keller@acme-ag.example"]
    ),
    lambda c: writes.log_interaction(c, "email", "2026-10-14", message_id=OFFER_ID),
    lambda c: writes.link_entities(c, EMAIL, source=CHAT, links=[{"relation": "cc", "to": "Hans"}]),
    lambda c: writes.create_task(c, "Call", HANS, EMAIL, related=["Acme AG"]),
    lambda c: writes.create_task(
        c, "Send the revised offer for Wartungsvertrag 2027", "Me", EMAIL, related=["Acme AG"]
    ),
    lambda c: writes.create_task(c, "Send the revised offer", "Me", EMAIL, match="new"),
    lambda c: writes.update_task(c, TASK, CHAT, status="done", note="x"),
    lambda c: reviews.propose(c, "duplicate", "Same?", ["Hans", HANS], ["x"], [], CHAT),
    lambda c: upkeep.create_missing_references(c),
    lambda c: upkeep.rename(c, "Wartungsvertrag 2027", "WV 2027", CHAT),
    lambda c: upkeep.rename(c, "Acme AG", "Acme Holding", CHAT),
    lambda c: upkeep.merge(c, HANS, "Hans", CHAT),
]


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("kind", NOTES)
def test_no_tool_fails_on_fields_a_hand_edit_left_in_odd_shapes(tmp_path, home, kind, shape):
    root = shutil.copytree(EXAMPLE, tmp_path / "vault")
    path = root / NOTES[kind]
    fields, body = frontmatter.read(path.read_text(encoding="utf-8"))
    for field in schema.TYPES[kind].fields[2:]:  # all but type and id, which make it the note it is
        fields[field.name] = SHAPES[shape](field, fields.get(field.name))
    path.write_text(frontmatter.render(fields, body), encoding="utf-8")
    with Crm(root, home, now=lambda: NOW) as crm:
        crm.refresh()
        assert str(path) in {i["path"] for i in lint.lint(crm)["issues"] if i["severity"] == "error"}
        for call in CALLS:
            with contextlib.suppress(OrbitError):
                call(crm)
