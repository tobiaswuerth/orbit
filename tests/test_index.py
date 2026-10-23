"""The index: built from the notes alone, incrementally, with unique values that record clashes instead of failing."""

import json
import os
import shutil
import sqlite3

import pytest

from orbit import index as index_module
from orbit.index import Index
from orbit.vault import Vault

from .conftest import EXAMPLE

HANS = "01_People/Hans Müller.md"


@pytest.fixture
def vault(tmp_path):
    shutil.copytree(EXAMPLE, tmp_path / "vault")
    return Vault(tmp_path / "vault")


@pytest.fixture
def index(vault, tmp_path):
    idx = Index(vault, index_module.location(vault.root, tmp_path / "home"))
    idx.sync()
    yield idx
    idx.close()


def dump(idx):
    """Everything the index holds, in a stable order."""
    tables = {
        "notes": "SELECT path, id, type, name, mtime_ns, size, sha256, fields, error FROM notes ORDER BY path",
        "claims": "SELECT * FROM claims ORDER BY kind, value, path",
        "identifiers": "SELECT * FROM identifiers ORDER BY kind, value, path",
        "links": "SELECT * FROM links ORDER BY path, field, target",
        "changes": "SELECT * FROM changes ORDER BY path, date, field",
        "search": "SELECT n.path, s.* FROM search s JOIN notes n ON n.num = s.rowid ORDER BY n.path",
    }
    return {table: [tuple(row) for row in idx.db.execute(sql)] for table, sql in tables.items()}


def test_the_example_vault_indexes_cleanly(index):
    assert index.counts() == {"person": 4, "organization": 1, "interaction": 2, "task": 2, "topic": 1, "review": 1}
    assert index.clashes() == []
    assert index.db.execute("SELECT count(*) FROM notes WHERE error IS NOT NULL").fetchone()[0] == 0
    row = index.row(HANS)
    assert (row["id"], row["type"], row["name"]) == ("per_01M4WNN540CGMAHYXV1R90AA5V", "person", "Hans Müller")
    assert json.loads(row["fields"])["job_title"] == "Leiter Einkauf"


def test_a_second_sync_changes_nothing(index):
    assert not index.sync()
    assert str(index.sync()) == "0 added, 0 changed, 0 removed"


def test_unique_values_have_one_holder(index):
    assert index.holder("email", "hans.mueller@acme-ag.example") == HANS
    assert index.holder("name", "hans müller") == HANS
    assert index.holder("id", "per_01M4WNN540CGMAHYXV1R90AA5V") == HANS
    assert index.holder("message_id", "<CAF3x9Q2kq7Lm@mail.gmail.com>").endswith("Segelwochenende Bodensee.md")
    assert index.holder("email", "nobody@x.example") is None


def test_identifiers_for_finding_candidates(index):
    def paths(kind, value):
        return [
            r[0] for r in index.db.execute("SELECT path FROM identifiers WHERE kind = ? AND value = ?", (kind, value))
        ]

    assert paths("key", "hans mueller") == [HANS]
    assert paths("sound", "657") == [HANS]
    assert paths("token", "hans") == [HANS, "01_People/Hans.md"]  # " " sorts before "."
    assert paths("phone", "521234567") == [HANS]
    assert paths("domain", "acme-ag.example") == ["01_People/Anna Keller.md", HANS, "02_Organizations/Acme AG.md"]
    assert paths("org", "acme") == ["02_Organizations/Acme AG.md"]
    assert paths("title", "wartungsvertrag 2027") == ["05_Topics/Wartungsvertrag 2027.md"]


def test_links_both_ways(index):
    into_acme = index.db.execute("SELECT path, field FROM links WHERE target_key = 'acme ag' ORDER BY path, field")
    assert [tuple(r) for r in into_acme] == [
        ("01_People/Anna Keller.md", "org"),
        (HANS, "org"),
        ("03_Interactions/2026/2026-10/2026-10-14 Email – AW Offerte Wartungsvertrag 2027.md", "orgs"),
        ("04_Tasks/Anna Keller to follow up on the technical clarification.md", "related"),
        ("04_Tasks/Send revised offer for Wartungsvertrag 2027.md", "related"),
        ("05_Topics/Wartungsvertrag 2027.md", "orgs"),
    ]
    out_of_hans = index.db.execute("SELECT field, target FROM links WHERE path = ? ORDER BY field, target", (HANS,))
    assert [tuple(r) for r in out_of_hans] == [
        (None, "2026-10-14 Email – AW Offerte Wartungsvertrag 2027"),
        (None, "2026-10-14 Email – AW Offerte Wartungsvertrag 2027"),
        (None, "2026-10-14 Email – AW Offerte Wartungsvertrag 2027"),
        ("colleague_of", "Anna Keller"),
        ("org", "Acme AG"),
    ]


def test_links_by_path_or_with_display_text(vault, index):
    vault.write("Inbox.md", "See [[01_People/Hans Müller.md|Hans]] and ![[Acme AG#Notes]].\n")
    index.sync()
    rows = index.db.execute("SELECT target, target_key FROM links WHERE path = 'Inbox.md' ORDER BY target")
    assert [tuple(r) for r in rows] == [("Acme AG", "acme ag"), ("Hans Müller", "hans müller")]


def test_history_lines_become_changes(index):
    (change,) = index.db.execute("SELECT date, field, old, new FROM changes WHERE path = ?", (HANS,))
    assert tuple(change) == ("2026-10-14", "created", None, "no candidate matched hans.mueller@acme-ag.example")


def test_full_text_search_finds_folded_names(index):
    def found(query):
        rows = index.db.execute(
            "SELECT n.path FROM search s JOIN notes n ON n.num = s.rowid WHERE search MATCH ?", (query,)
        )
        return [r[0] for r in rows]

    assert found("mueller") == [HANS, "01_People/Hans.md", "90_Review/2026-10-18 Duplicate – Hans and Hans Müller.md"]
    assert found("roles: einkauf") == [HANS]
    assert found("emails: acme") == ["01_People/Anna Keller.md", HANS, "02_Organizations/Acme AG.md"]
    assert found("text: budget") == [
        HANS,
        "03_Interactions/2026/2026-10/2026-10-14 Email – AW Offerte Wartungsvertrag 2027.md",
        "05_Topics/Wartungsvertrag 2027.md",
    ]
    assert found("text: created") == []  # history lines aren't searched


def test_deleting_the_database_gives_an_identical_index(vault, index, tmp_path):
    before = dump(index)
    index.close()
    for suffix in ("", "-wal", "-shm"):
        index.path.with_name(index.path.name + suffix).unlink(missing_ok=True)
    again = Index(vault, index.path)
    again.sync()
    assert dump(again) == before
    again.close()


def test_an_index_opened_again_keeps_what_it_holds(vault, index):
    before = dump(index)
    index.close()
    again = Index(vault, index.path)
    assert dump(again) == before
    assert not again.sync()
    again.close()


def test_rebuild_gives_an_identical_index(index):
    before = dump(index)
    assert len(index.rebuild().added) == 11
    assert dump(index) == before


def test_changed_notes_are_indexed_again(vault, index):
    path = vault.path(HANS)
    path.write_text(path.read_text(encoding="utf-8").replace("Leiter Einkauf", "Head of Procurement"), encoding="utf-8")
    assert index.sync().changed == [HANS]
    assert json.loads(index.row(HANS)["fields"])["job_title"] == "Head of Procurement"


def test_touched_notes_are_read_but_not_indexed_again(vault, index):
    stat = vault.path(HANS).stat()
    os.utime(vault.path(HANS), ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
    num = index.row(HANS)["num"]
    assert not index.sync()
    assert index.row(HANS)["mtime_ns"] == stat.st_mtime_ns + 10**9
    assert index.row(HANS)["num"] == num


def test_removed_notes_leave_the_index(vault, index):
    vault.path(HANS).unlink()
    assert index.sync().removed == [HANS]
    assert index.row(HANS) is None
    assert index.holder("email", "hans.mueller@acme-ag.example") is None
    assert index.db.execute("SELECT count(*) FROM search").fetchone()[0] == 10


def test_a_note_gone_between_listing_and_reading_is_removed(vault, index, monkeypatch):
    read = vault.read

    def gone(rel):
        if rel == HANS:
            raise FileNotFoundError(rel)
        return read(rel)

    stat = vault.path(HANS).stat()
    os.utime(vault.path(HANS), ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
    monkeypatch.setattr(vault, "read", gone)
    assert index.sync().removed == [HANS]


def test_refresh_given_notes(vault, index):
    vault.write("01_People/Neu.md", "---\ntype: person\nname: Neu\n---\n")
    vault.path(HANS).unlink()
    report = index.refresh(["01_People/Neu.md", HANS, "01_People/Never.md", "01_People/Anna Keller.md"])
    assert (report.added, report.changed, report.removed) == (["01_People/Neu.md"], [], [HANS])


def test_a_planted_duplicate_is_recorded_as_a_clash(vault, index):
    copy = "01_People/Hans Müller copy.md"
    shutil.copyfile(vault.path(HANS), vault.path(copy))
    assert index.sync().added == [copy]
    # The copy comes first in path order, so it holds the values; Hans Müller's note clashes with it.
    assert index.clashes() == [
        {"kind": "email", "value": "hans.mueller@acme-ag.example", "path": HANS, "holder": copy},
        {"kind": "id", "value": "per_01M4WNN540CGMAHYXV1R90AA5V", "path": HANS, "holder": copy},
    ]
    vault.path(copy).unlink()
    index.sync()
    assert index.clashes() == []
    assert index.holder("email", "hans.mueller@acme-ag.example") == HANS


def test_clashes_dont_depend_on_the_order_notes_arrive_in(vault, index, tmp_path):
    shutil.copyfile(vault.path(HANS), vault.path("01_People/Zz.md"))
    shutil.copyfile(vault.path(HANS), vault.path("01_People/Aa.md"))
    index.refresh(["01_People/Zz.md"])
    index.refresh(["01_People/Aa.md"])
    incremental = index.clashes()
    fresh = Index(vault, tmp_path / "fresh.sqlite")
    fresh.sync()
    assert fresh.clashes() == incremental
    assert {c["holder"] for c in incremental} == {"01_People/Aa.md"}
    fresh.close()


def test_a_note_listing_an_address_twice_doesnt_clash_with_itself(vault, index):
    vault.write(
        "01_People/Twice.md", "---\ntype: person\nname: Twice\nemails:\n  - t@x.example\n  - T@x.example\n---\n"
    )
    index.sync()
    assert index.clashes() == []


def test_unreadable_notes_are_recorded(vault, index):
    vault.write("01_People/Broken.md", "---\ntype: person\norg:\n  name: Acme\n---\n")
    vault.path("01_People/Binary.md").write_bytes(b"\xff\xfe\x00")
    vault.write("Plain.md", "Just text with a [[Hans Müller]] link.\n")
    index.sync()
    errors = dict(index.db.execute("SELECT path, error FROM notes WHERE error IS NOT NULL").fetchall())
    assert errors == {
        "01_People/Binary.md": "not UTF-8 text",
        "01_People/Broken.md": "unreadable front matter, line 4: "
        "nested mappings and multi-line values aren't supported",
    }
    assert index.holder("name", "broken") == "01_People/Broken.md"
    assert index.row("Plain.md")["type"] is None
    assert index.counts()[None] == 3


def test_an_index_of_another_version_is_built_again(vault, index):
    index.db.execute("PRAGMA user_version = 0")
    index.close()
    again = Index(vault, index.path)
    assert again.counts() == {}
    assert len(again.sync().added) == 11
    again.close()


def test_a_failed_sync_leaves_the_index_as_it_was(vault, index, monkeypatch):
    before = dump(index)
    vault.write("01_People/New.md", "---\ntype: person\nname: New\n---\n")

    def fail(rel):
        raise OSError("disk gone")

    monkeypatch.setattr(vault, "read", fail)
    with pytest.raises(OSError, match="disk gone"):
        index.sync()
    assert dump(index) == before


def test_location_is_one_database_per_vault(tmp_path):
    a = index_module.location(tmp_path / "crm", tmp_path / "home")
    assert a == index_module.location(tmp_path / "crm" / ".." / "crm", tmp_path / "home")
    assert a != index_module.location(tmp_path / "other" / "crm", tmp_path / "home")
    assert a.parent == tmp_path / "home" / "indexes"
    assert a.name.startswith("crm-")
    assert index_module.location(tmp_path / "!!!", tmp_path).name.startswith("vault-")


def test_wal_mode(index):
    assert index.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    with pytest.raises(sqlite3.IntegrityError):
        index.db.execute(
            "INSERT INTO claims (kind, value, path, owner) VALUES ('email', 'hans.mueller@acme-ag.example', ?, 1)",
            ("01_People/Anna Keller.md",),
        )
