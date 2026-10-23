"""Opening a vault: one writer per vault, an index kept up to date, and edits made elsewhere picked up."""

import logging
import re
import time

import anyio
import pytest

from orbit import crm as crm_module
from orbit import index, watch
from orbit.crm import Crm
from orbit.errors import OrbitError

from .conftest import NOW

HANS = "01_People/Hans Müller.md"


def test_only_a_vault_opens(tmp_path, home):
    with pytest.raises(OrbitError, match=r"is not an orbit vault: it has no 99_System/orbit\.toml\. Run `orbit init`"):
        Crm(tmp_path, home)


def test_a_broken_configuration_stops_it_from_opening(example, home):
    (example / "99_System" / "orbit.toml").write_text("me = 1", encoding="utf-8")
    with pytest.raises(OrbitError, match=r"me must be the id of Me\.md"):
        Crm(example, home)


def test_one_writer_per_vault(example, home):
    with Crm(example, home), pytest.raises(OrbitError, match="another orbit process is using"):
        Crm(example, home)
    with Crm(example, home):  # free again once the first is closed
        pass


def test_the_index_lives_in_orbit_home(crm, home):
    assert crm.index.path.parent == home / "indexes"
    assert not list(crm.vault.root.rglob("*.sqlite"))


def test_today_is_by_the_clock(crm):
    assert crm.today() == NOW.date().isoformat() == "2026-10-22"


def test_refresh_given_paths(crm):
    crm.vault.write("01_People/New.md", "---\ntype: person\nname: New\n---\n")
    report = crm.refresh({"01_People/New.md", "01_People/.New.md.1.tmp", "01_People/photo.png"})
    assert report.added == ["01_People/New.md"]


def test_refresh_reads_configuration_changes(crm):
    assert "anni" not in crm.vault.nicknames.variants("anna")
    crm.vault.path("99_System/nicknames.txt").write_text("Anna = Anni\n", encoding="utf-8")
    assert "anni" not in crm.vault.nicknames.variants("anna")  # until told
    crm.refresh({"99_System/nicknames.txt"})
    assert "anni" in crm.vault.nicknames.variants("anna")


def test_refresh_after_a_folder_changed_syncs_everything(crm):
    crm.vault.path("05_Topics").rename(crm.vault.path("06_Projects"))
    report = crm.refresh({"05_Topics", "06_Projects"})
    assert report.added == ["06_Projects/Wartungsvertrag 2027.md"]
    assert report.removed == ["05_Topics/Wartungsvertrag 2027.md"]


def run_watching(crm, steps):
    """Watch the vault while `steps` run: (action, condition) pairs, each action done in a thread, then waited on
    until its condition holds. How long each condition took to hold."""

    async def main():
        stop, taken = anyio.Event(), []
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(watch.watch, crm, stop)
            await anyio.sleep(0.3)  # the watcher is up
            try:
                for action, condition in steps:
                    await anyio.to_thread.run_sync(action)
                    start = time.perf_counter()
                    with anyio.fail_after(10):
                        while not condition():
                            await anyio.sleep(0.01)
                    taken.append(time.perf_counter() - start)
            finally:
                stop.set()
        return taken

    return anyio.run(main)


def test_edits_made_elsewhere_are_indexed_within_a_second(crm):
    path = crm.vault.path(HANS)

    def edit():
        path.write_text(path.read_text(encoding="utf-8").replace("Leiter Einkauf", "Head of Procurement"), "utf-8")

    (seconds,) = run_watching(crm, [(edit, lambda: "Head of Procurement" in crm.index.row(HANS)["fields"])])
    assert seconds < 3  # typically 0.1 s; generous, so a busy CI machine doesn't fail it


def test_the_watcher_passes_over_hidden_folders_and_says_nothing(crm, monkeypatch, caplog):
    # Obsidian rewrites .obsidian/workspace.json whenever a note is opened: no reason to wake the watcher, or to log.
    caplog.set_level(logging.INFO)
    seen = []
    monkeypatch.setattr(crm, "refresh", lambda paths: seen.append(set(paths)))
    workspace = crm.vault.root / ".obsidian" / "workspace.json"
    workspace.parent.mkdir(exist_ok=True)
    inbox = crm.vault.path("Inbox.md")
    run_watching(
        crm,
        [
            (lambda: workspace.write_text("{}", encoding="utf-8"), lambda: True),
            (lambda: inbox.write_text("one", encoding="utf-8"), lambda: any("Inbox.md" in s for s in seen)),
        ],
    )
    assert not [p for paths in seen for p in paths if p.startswith(".")]
    assert "change" not in caplog.text


def test_the_watcher_survives_a_failed_refresh(crm, monkeypatch, capsys):
    # Only the changes to Inbox.md count: on macOS, the watcher may first report the folders the test vault was
    # created in, just before it started.
    inboxes = []

    def refresh(paths):
        if "Inbox.md" in paths:
            inboxes.append(paths)
            if len(inboxes) == 1:
                raise OSError("in use")

    monkeypatch.setattr(crm, "refresh", refresh)
    inbox = crm.vault.path("Inbox.md")
    run_watching(
        crm,
        [
            (lambda: inbox.write_text("one", encoding="utf-8"), lambda: len(inboxes) >= 1),
            (lambda: inbox.write_text("two", encoding="utf-8"), lambda: len(inboxes) >= 2),
        ],
    )
    assert re.search(r"warning: couldn't index changes to .*Inbox\.md.*: in use", capsys.readouterr().err)


def test_the_watcher_survives_an_unexpected_error_and_logs_it(crm, monkeypatch, capsys, caplog):
    # A bug met on one edit mustn't stop the server, which runs the watcher beside it; its traceback goes to the log.
    inboxes = []

    def refresh(paths):
        if "Inbox.md" in paths:
            inboxes.append(paths)
            if len(inboxes) == 1:
                raise KeyError("decision")

    monkeypatch.setattr(crm, "refresh", refresh)
    inbox = crm.vault.path("Inbox.md")
    run_watching(
        crm,
        [
            (lambda: inbox.write_text("one", encoding="utf-8"), lambda: len(inboxes) >= 1),
            (lambda: inbox.write_text("two", encoding="utf-8"), lambda: len(inboxes) >= 2),
        ],
    )
    assert re.search(r"warning: couldn't index changes to .*Inbox\.md.*: KeyError: 'decision'", capsys.readouterr().err)
    assert "indexing changes failed" in caplog.text
    assert "Traceback" in caplog.text


def test_a_name_too_common_is_refused(crm, monkeypatch):
    monkeypatch.setattr(crm.index, "holder", lambda kind, value: "taken.md")
    with pytest.raises(OrbitError, match="too many notes are called Hans; give a more distinctive name"):
        crm.new("person", "01_People", "Hans", {"name": "Hans"}, [])


def test_a_note_gone_since_it_was_indexed(crm):
    crm.vault.path(HANS).unlink()
    with pytest.raises(OrbitError, match=r"01_People/Hans Müller\.md is gone from the vault; find the note again"):
        crm.load(HANS)


def test_a_note_that_isnt_text_is_named_when_loaded(crm):
    crm.vault.path(HANS).write_bytes(b"---\nname: \xff\n---\n")
    with pytest.raises(OrbitError, match=r"Hans Müller\.md can't be read: it isn't UTF-8 text; fix it by hand"):
        crm.load(HANS)


def test_a_damaged_index_is_built_again(example, home):
    with Crm(example, home) as crm:
        crm.refresh()
        path = crm.index.path
    path.write_bytes(b"this is not a database, but a disk's bad day" * 100)
    with Crm(example, home) as crm:
        assert crm.refresh().added  # built from the notes again
        assert crm.find("Hans Müller").id == "per_01M4WNN540CGMAHYXV1R90AA5V"


def test_an_index_that_cant_be_opened_at_all_fails_with_the_file_systems_error(example, home):
    path = index.location(example, home)
    path.mkdir(parents=True)  # a folder where the index should be: SQLite can't open it, orbit can't delete it
    with pytest.raises(OSError, match=re.escape(path.name)):
        Crm(example, home)
    path.rmdir()
    with Crm(example, home) as crm:  # not left locked
        assert crm.refresh().added


def test_a_vault_that_fails_to_open_is_not_left_locked(example, home, monkeypatch):
    def broken(*args):
        raise OSError("disk gone")

    with monkeypatch.context() as patch:
        patch.setattr(crm_module, "Index", broken)
        with pytest.raises(OSError, match="disk gone"):
            Crm(example, home)
    with Crm(example, home):  # the lock is free again
        pass
