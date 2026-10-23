"""Phase 2's measure: the example vault rebuilt from an empty one through orbit's tools alone, note for note."""

import datetime

from orbit import reviews, vault, writes
from orbit.crm import Crm

from .conftest import EXAMPLE
from .scenario import OWNER, STEPS, without_ids

TOOLS = {
    "log_interaction": writes.log_interaction,
    "upsert_person": writes.upsert_person,
    "upsert_organization": writes.upsert_organization,
    "upsert_topic": writes.upsert_topic,
    "link_entities": writes.link_entities,
    "add_observation": writes.add_observation,
    "create_task": writes.create_task,
    "propose_review": reviews.propose,
}


def at(day):
    return datetime.datetime.fromisoformat(f"{day}T12:00:00+02:00")


def notes(root):
    return {
        p.relative_to(root).as_posix(): p.read_text(encoding="utf-8") for p in sorted(root.rglob("*")) if p.is_file()
    }


def test_the_example_vault_rebuilt_through_the_tools(tmp_path, home):
    root = tmp_path / "crm"
    vault.init(root, *OWNER, now=at("2026-10-01"))
    with Crm(root, home) as crm:
        crm.refresh()
        for day, tool, arguments in STEPS:
            crm.now = lambda day=day: at(day)
            TOOLS[tool](crm, **arguments)
    built, example = notes(root), notes(EXAMPLE)
    assert list(built) == list(example)
    for path, text in example.items():
        assert without_ids(built[path]) == without_ids(text), path


def test_calling_every_step_again_changes_nothing(tmp_path, home):
    root = tmp_path / "crm"
    vault.init(root, *OWNER, now=at("2026-10-01"))
    with Crm(root, home) as crm:
        crm.refresh()
        for day, tool, arguments in STEPS:
            crm.now = lambda day=day: at(day)
            TOOLS[tool](crm, **arguments)
        before = notes(root)
        crm.now = lambda: at("2026-10-20")
        for _, tool, arguments in STEPS:
            result = TOOLS[tool](crm, **arguments)
            assert result.get("changed", []) == [], (tool, result)
    assert notes(root) == before
