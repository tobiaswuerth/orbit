"""The Obsidian Bases views `orbit init` writes: valid YAML, in the documented syntax, about fields that exist."""

import datetime
import re

import pytest
import yaml

from orbit import bases, schema, vault

FILES = ["People.base", "Follow-ups.base", "Review.base"]
FIELD = re.compile(r"(?<![\w.\"])(?:note\.)?([a-z_]+)\b(?!\s*\()")
FUNCTIONS = {"date", "today", "now", "if", "file", "and", "or", "not", "true", "false", "this", "formula"}


def test_the_bases_and_their_views():
    found = bases.templates()
    assert list(found) == FILES
    views = {name: [v["name"] for v in yaml.safe_load(text)["views"]] for name, text in found.items()}
    assert views == {
        "People.base": ["People", "By organization", "Not contacted for a year", "To confirm"],
        "Follow-ups.base": ["Open tasks", "Waiting for others", "People to follow up"],
        "Review.base": ["Pending reviews", "Answered"],
    }


def filters(node):
    """Every filter statement in a filter tree."""
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for value in node.values() for s in filters(value)]
    return [s for item in node for s in filters(item)]


@pytest.mark.parametrize("name", FILES)
def test_views_use_the_documented_keys_and_existing_fields(name):
    base = yaml.safe_load(bases.templates()[name])
    assert set(base) <= {"filters", "formulas", "properties", "summaries", "views"}
    for view in base["views"]:
        assert set(view) <= {"type", "name", "limit", "filters", "order", "sort", "groupBy", "summaries"}, view
        assert view["type"] == "table"
        everything = [*filters(base.get("filters", [])), *filters(view.get("filters", []))]
        folders = re.findall(r'file\.inFolder\("([^"]+)"\)', " ".join(everything))
        (folder,) = set(folders)
        (kind,) = [t for t in schema.TYPES.values() if t.folder == folder]
        statements = everything
        used = [*view.get("order", []), *(s["property"] for s in view.get("sort", []))]
        used += [view["groupBy"]["property"]] if "groupBy" in view else []
        used += [m for s in statements for m in FIELD.findall(re.sub(r'"[^"]*"', '""', s))]
        for field in used:
            name_ = field.removeprefix("note.")
            if name_.startswith("file.") or name_ in FUNCTIONS:
                continue
            assert kind.field(name_), f"{name}: {view['name']} uses {field}, which a {kind.name} doesn't have"
        for sort in view.get("sort", []):
            assert sort["direction"] in ("ASC", "DESC")


def test_init_writes_the_bases(tmp_path):
    created = vault.init(tmp_path, now=datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC))
    assert [p for p in created if p.startswith("95_Bases")] == ["95_Bases/", *(f"95_Bases/{f}" for f in FILES)]
    for name, text in bases.templates().items():
        assert (tmp_path / "95_Bases" / name).read_text(encoding="utf-8") == text
    (tmp_path / "95_Bases" / "People.base").write_text("mine", encoding="utf-8")
    (tmp_path / "95_Bases" / "Review.base").unlink()
    assert vault.init(tmp_path) == ["95_Bases/Review.base"]
    assert (tmp_path / "95_Bases" / "People.base").read_text(encoding="utf-8") == "mine"
