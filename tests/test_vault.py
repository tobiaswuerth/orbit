"""A vault's files: which are notes, reading and atomic writing, and `orbit init`."""

import datetime
import os
import shutil

import pytest

from orbit import config, vault
from orbit.errors import OrbitError
from orbit.sections import Body
from orbit.vault import Note, Vault

from .conftest import EXAMPLE

NOW = datetime.datetime(2026, 10, 1, 8, 0, tzinfo=datetime.UTC)


def test_files_are_the_notes(tmp_path):
    shutil.copytree(EXAMPLE, tmp_path, dirs_exist_ok=True)
    for extra in [".obsidian/workspace.md", ".trash/old.md", "01_People/.Hans.md.1.tmp", "95_Bases/People.md"]:
        (tmp_path / extra).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / extra).write_text("x", encoding="utf-8")
    (tmp_path / "01_People" / "photo.png").write_bytes(b"")
    (tmp_path / "Inbox.md").write_text("loose note", encoding="utf-8")
    files = Vault(tmp_path).files()
    assert list(files) == [
        "01_People/Anna Keller.md",
        "01_People/Hans Müller.md",
        "01_People/Hans.md",
        "01_People/Me.md",
        "02_Organizations/Acme AG.md",
        "03_Interactions/2026/2026-10/2026-10-14 Email – AW Offerte Wartungsvertrag 2027.md",
        "03_Interactions/2026/2026-10/2026-10-18 Email – Segelwochenende Bodensee.md",
        "04_Tasks/Anna Keller to follow up on the technical clarification.md",
        "04_Tasks/Send revised offer for Wartungsvertrag 2027.md",
        "05_Topics/Wartungsvertrag 2027.md",
        "90_Review/2026-10-18 Duplicate – Hans and Hans Müller.md",
        "Inbox.md",
    ]
    stat = (tmp_path / "Inbox.md").stat()
    assert files["Inbox.md"] == (stat.st_mtime_ns, stat.st_size)


def test_note_paths():
    assert vault.is_note_path("01_People/Hans Müller.md")
    assert not vault.is_note_path("99_System/AGENTS.md")
    assert not vault.is_note_path(".obsidian/x.md")
    assert not vault.is_note_path("01_People/.Hans.md.4711.tmp")
    assert not vault.is_note_path("01_People/photo.png")


def test_paths_in_the_vault(tmp_path):
    v = Vault(tmp_path)
    assert v.rel(tmp_path / "01_People" / "Me.md") == "01_People/Me.md"
    assert v.rel(tmp_path.parent / "elsewhere.md") is None
    assert v.rel(tmp_path) is None  # macOS reports changes to the vault folder itself: no file, nothing to index
    assert v.stat("missing.md") is None
    v.write("a.md", "abc")
    assert v.stat("a.md") == ((tmp_path / "a.md").stat().st_mtime_ns, 3)


def test_notes_parse_and_render_unchanged():
    path = "01_People/Hans Müller.md"
    text = (EXAMPLE / path).read_text(encoding="utf-8")
    note = Vault(EXAMPLE).note(path)
    assert (note.name, note.type, note.fields["id"]) == ("Hans Müller", "person", "per_01M4WNN540CGMAHYXV1R90AA5V")
    assert note.text() == text


def test_an_unchanged_note_renders_as_it_was_written():
    text = "---\n# mine\nname: Hans   \nid: per_01M4WNN540CGMAHYXV1R90AA5V\ntype: person\nport: 8775\n---\nbody\n"
    assert Note.parse("x.md", text).text() == text
    assert Note.parse("x.md", "plain text\n").text() == "plain text\n"
    assert Note.parse("x.md", "plain text\n").type is None


def test_a_changed_note_keeps_the_lines_of_unchanged_fields_in_schema_order():
    text = "---\nname: Hans\nport: 8775\nlist:\n- a\nid: per_01M4WNN540CGMAHYXV1R90AA5V\ntype: person\n---\nbody\n"
    note = Note.parse("x.md", text)
    note.fields["job_title"] = "Leiter Einkauf"
    note.fields["name"] = "Hans Müller"
    assert note.text() == (
        "---\ntype: person\nid: per_01M4WNN540CGMAHYXV1R90AA5V\nname: Hans Müller\njob_title: Leiter Einkauf\n"
        "port: 8775\nlist:\n- a\n---\nbody\n"
    )
    other = Note.parse("x.md", "---\ntype: meeting\nb: 1\na: 2\n---\n")
    other.fields["c"] = "3"
    assert other.text() == '---\ntype: meeting\nb: 1\na: 2\nc: "3"\n---\n'


def test_a_new_note_renders_its_fields():
    note = Note(
        "01_People/Hans.md", {"type": "person", "name": "Hans", "id": "per_01M4WNN540CGMAHYXV1R90AA5V"}, Body([[]])
    )
    assert note.text() == "---\ntype: person\nid: per_01M4WNN540CGMAHYXV1R90AA5V\nname: Hans\n---\n"


def test_write_is_atomic_with_unix_line_ends(tmp_path):
    v = Vault(tmp_path)
    v.write("01_People/Hans.md", "a\nb\n")
    assert (tmp_path / "01_People" / "Hans.md").read_bytes() == b"a\nb\n"
    v.write("01_People/Hans.md", "c\n")
    assert v.read("01_People/Hans.md") == b"c\n"
    assert os.listdir(tmp_path / "01_People") == ["Hans.md"]


def test_write_waits_for_a_file_another_program_holds(tmp_path, monkeypatch):
    replace, refusals = os.replace, []

    def busy(src, dst):
        if len(refusals) < 2:
            refusals.append(dst)
            raise PermissionError("in use")
        replace(src, dst)

    monkeypatch.setattr(os, "replace", busy)
    Vault(tmp_path).write("a.md", "x")
    assert len(refusals) == 2
    assert (tmp_path / "a.md").read_text(encoding="utf-8") == "x"


def test_rename_and_trash_wait_for_a_file_another_program_holds(tmp_path, monkeypatch):
    v = Vault(tmp_path)
    v.write("a.md", "a")
    replace, refusals = os.replace, []

    def busy(src, dst):
        if len(refusals) % 3 < 2:
            refusals.append(dst)
            raise PermissionError("in use")
        refusals.append(None)
        replace(src, dst)

    monkeypatch.setattr(os, "replace", busy)
    monkeypatch.setattr(vault.time, "sleep", lambda seconds: None)
    v.rename("a.md", "b.md")
    assert v.trash("b.md") == ".trash/b.md"
    assert len(refusals) == 6
    assert (tmp_path / ".trash" / "b.md").read_text(encoding="utf-8") == "a"


def test_write_gives_up_and_leaves_no_temporary_file(tmp_path, monkeypatch):
    def busy(src, dst):
        raise PermissionError("in use")

    monkeypatch.setattr(os, "replace", busy)
    monkeypatch.setattr(vault.time, "sleep", lambda seconds: None)
    with pytest.raises(PermissionError):
        Vault(tmp_path).write("a.md", "x")
    assert os.listdir(tmp_path) == []


def test_init_creates_a_vault(tmp_path):
    root = tmp_path / "crm"
    created = vault.init(root, "Max", ["Max@MeineFirma.example", "max.privat@mail.example"], NOW)
    assert created == [
        "01_People/",
        "02_Organizations/",
        "03_Interactions/",
        "04_Tasks/",
        "05_Topics/",
        "90_Review/",
        "95_Bases/",
        "99_System/",
        "01_People/Me.md",
        "99_System/orbit.toml",
        "99_System/nicknames.txt",
        "99_System/AGENTS.md",
        "95_Bases/People.base",
        "95_Bases/Follow-ups.base",
        "95_Bases/Review.base",
    ]
    me = Vault(root).note("01_People/Me.md")
    example = Vault(EXAMPLE).note("01_People/Me.md")
    assert me.text().replace(me.fields["id"], example.fields["id"]) == example.text()
    assert Vault(root).config.me == me.fields["id"]
    for rel in ["99_System/nicknames.txt", "99_System/AGENTS.md"]:
        assert (root / rel).read_text(encoding="utf-8") == (EXAMPLE / rel).read_text(encoding="utf-8")


def test_init_leaves_what_exists(tmp_path):
    vault.init(tmp_path, now=NOW)
    (tmp_path / "99_System" / "orbit.toml").unlink()
    (tmp_path / "99_System" / "AGENTS.md").write_text("mine", encoding="utf-8")
    assert vault.init(tmp_path, "Someone", now=NOW) == ["99_System/orbit.toml"]
    me = Vault(tmp_path).note("01_People/Me.md")
    assert me.fields["name"] == "Me"
    assert "emails" not in me.fields
    assert config.load(tmp_path / "99_System" / "orbit.toml").me == me.fields["id"]
    assert (tmp_path / "99_System" / "AGENTS.md").read_text(encoding="utf-8") == "mine"


@pytest.mark.parametrize("text", ["# mine\n", "---\ntype: person\nname: Me\n---\n", "---\nid: [\n---\n"])
def test_init_refuses_to_name_a_me_without_an_id_and_changes_nothing(tmp_path, text):
    (tmp_path / "01_People").mkdir()
    (tmp_path / "01_People" / "Me.md").write_text(text, encoding="utf-8")
    with pytest.raises(OrbitError, match=r"01_People/Me\.md has no person's id for orbit\.toml"):
        vault.init(tmp_path, now=NOW)
    assert [p.name for p in tmp_path.iterdir()] == ["01_People"]


def test_init_adds_what_lacks_beside_a_me_without_an_id_once_orbit_toml_exists(tmp_path):
    vault.init(tmp_path, now=NOW)
    (tmp_path / "01_People" / "Me.md").write_text("# mine\n", encoding="utf-8")
    (tmp_path / "95_Bases" / "People.base").unlink()
    assert vault.init(tmp_path, now=NOW) == ["95_Bases/People.base"]


@pytest.mark.parametrize(
    "text, addresses",
    [
        (None, []),
        ("---\nid: [\n---\n", []),
        ("---\ntype: person\nname: Me\n---\n", []),
        ("---\ntype: person\nemails: max@meinefirma.example\n---\n", ["max@meinefirma.example"]),
        ("---\ntype: person\nemails:\n  - a@x.example\n  - ''\n  - b@x.example\n---\n", ["a@x.example", "b@x.example"]),
    ],
)
def test_my_addresses(tmp_path, text, addresses):
    if text is not None:
        Vault(tmp_path).write(vault.ME, text)
    assert vault.my_addresses(tmp_path) == addresses


def test_files_leaves_out_a_file_gone_since_its_folder_was_listed(tmp_path, monkeypatch):
    v = Vault(tmp_path)
    v.write("a.md", "a")
    v.write("b.md", "b")
    real = os.stat

    def stat(path, *args, **kwargs):
        if str(path).endswith("a.md"):  # deleted in between, or a link that leads nowhere
            raise FileNotFoundError(path)
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", stat)
    assert list(v.files()) == ["b.md"]


def test_nicknames_saved_with_a_byte_order_mark(tmp_path):
    vault.init(tmp_path, now=NOW)
    (tmp_path / "99_System" / "nicknames.txt").write_text("Hans = Hansi\n", encoding="utf-8-sig")
    assert "hansi" in Vault(tmp_path).nicknames.variants("hans")


def test_nicknames_that_are_not_utf8(tmp_path):
    vault.init(tmp_path, now=NOW)
    (tmp_path / "99_System" / "nicknames.txt").write_text("Jakob = Köbi\n", encoding="cp1252")
    with pytest.raises(OrbitError, match=r"nicknames\.txt isn't UTF-8 text; save it as UTF-8"):
        Vault(tmp_path).nicknames  # noqa: B018


def test_config_and_nicknames_reload(tmp_path):
    v = Vault(tmp_path)
    assert v.config.me is None
    assert v.nicknames.variants("hansi") == {"hansi"}
    vault.init(tmp_path, now=NOW)
    assert v.config.me is None  # read once
    v.reload()
    assert v.config.me is not None
    assert "hans" in v.nicknames.variants("hansi")


def test_rename_and_trash(tmp_path):
    v = Vault(tmp_path)
    v.write("a.md", "a")
    v.write("b.md", "b")
    with pytest.raises(FileExistsError, match=r"b\.md exists already"):
        v.rename("a.md", "b.md")
    v.rename("a.md", "A.md")  # a change of case alone
    assert v.path("A.md").read_text(encoding="utf-8") == "a"
    assert v.trash("A.md") == ".trash/A.md"
    v.write("A.md", "again")
    assert v.trash("A.md") == ".trash/A (2).md"
    assert sorted(p.name for p in (tmp_path / ".trash").iterdir()) == ["A (2).md", "A.md"]
