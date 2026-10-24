"""lint_vault: the rules a vault edited by hand can break, found, and the safe ones fixed."""

from orbit.lint import lint

HANS = "01_People/Hans Müller.md"


def edit(crm, path, old, new):
    note = crm.vault.path(path)
    note.write_text(note.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")


def rules(result):
    return [(i["severity"], i["note"], i["rule"], i["message"]) for i in result["issues"]]


def test_the_example_vault_is_clean(crm):
    assert lint(crm) == {"issues": [], "counts": {"error": 0, "warning": 0}, "fixed": []}


def test_finds_a_planted_unknown_field_and_a_broken_link(crm):
    edit(crm, HANS, "job_title:", "mood: cheerful\njob_title:")
    edit(crm, HANS, "## Notes\n", "## Notes\nMet him with [[Peter Brand]] at the fair.\n")
    edit(crm, "01_People/Anna Keller.md", '"[[Acme AG]]"', '"[[Acme Ltd]]"')
    result = lint(crm)
    assert rules(result) == [
        ("warning", "Anna Keller", "broken link", "[[Acme Ltd]] in org leads to no note"),
        ("warning", "Hans Müller", "broken link", "[[Peter Brand]] leads to no note"),
        ("warning", "Hans Müller", "unknown field", "mood is kept, but isn't part of the person schema"),
    ]
    assert result["counts"] == {"error": 0, "warning": 3}
    assert result["issues"][0]["path"] == str(crm.vault.path("01_People/Anna Keller.md"))


def test_a_name_that_isnt_its_file_s_is_named(crm):
    # A person's name was set to the one a later email gave: the file, and every link to it, kept the old one.
    edit(crm, HANS, "name: Hans Müller", "name: Hans Peter Müller")
    assert rules(lint(crm)) == [
        ("warning", "Hans Müller", "name not the file's",
         "its name 'Hans Peter Müller' isn't its file's: rename_entity to its name renames the file and the links to "
         "it; to the file's, it sets the name"),
    ]  # fmt: skip


def test_a_name_differing_from_its_file_s_only_where_files_must_is_fine(crm):
    # Me.md keeps its file name whatever the owner is called; a second note of one name gets a number or what tells it
    # apart; a name holds characters no file name may, or differs only in case.
    edit(crm, HANS, "name: Hans Müller", "name: hans müller")
    for path, kind, ref, name in [
        ("01_People/Hans Müller (2).md", "person", "per_01M4WNN540CGMAHYXV1R90AB00", "Hans Müller"),
        ("01_People/Hans Müller (Beta).md", "person", "per_01M4WNN540CGMAHYXV1R90AB02", "Hans Müller"),
        ("02_Organizations/ACDC Ltd.md", "organization", "org_01M4WNN540CGMAHYXV1R90AB01", "AC/DC Ltd"),
    ]:
        crm.vault.path(path).write_text(f"---\ntype: {kind}\nid: {ref}\nname: {name}\n---\n", encoding="utf-8")
    assert [i for i in rules(lint(crm)) if i[2] == "name not the file's"] == []


def test_links_to_attachments_that_exist_are_fine(crm):
    edit(crm, HANS, "## Notes\n", "## Notes\n![[card.png]] and [[gone.pdf]]\n")
    (crm.vault.root / "01_People" / "Card.PNG").write_bytes(b"")
    assert rules(lint(crm)) == [("warning", "Hans Müller", "broken link", "[[gone.pdf]] leads to no note")]


def test_links_to_the_bases_views_and_system_files_are_fine(crm):
    """Obsidian links to any file in the vault: a note may embed the views orbit init writes, or link its AGENTS.md."""
    edit(crm, HANS, "## Notes\n", "## Notes\n![[Follow-ups.base]], [[95_Bases/People.base]], [[AGENTS]] and [[Gone]]\n")
    assert rules(lint(crm)) == [("warning", "Hans Müller", "broken link", "[[Gone]] leads to no note")]


def test_finds_schema_problems_clashes_and_unreadable_notes(crm):
    edit(crm, "01_People/Anna Keller.md", "context: professional", "context: work")
    crm.vault.write("01_People/Hans Kopie.md", crm.vault.path(HANS).read_text(encoding="utf-8"))
    crm.vault.write("01_People/Broken.md", "---\ntype: person\norg:\n  name: Acme\n---\n")
    crm.vault.write("02_Organizations/Loose.md", "Just some text.\n")
    crm.vault.write("Inbox.md", "Loose, and fine.\n")
    crm.vault.write(
        "05_Topics/Hans Moved.md", "---\ntype: person\nid: per_01M57ZJKJ8HWCPYDPQSTB9FCHA\nname: Moved\n---\n"
    )
    crm.vault.write("01_People/Odd.md", "---\ntype: gadget\n---\n")
    assert rules(lint(crm)) == [
        ("error", "Anna Keller", "schema", "context: 'work' is not one of professional, personal, both"),
        (
            "error",
            "Broken",
            "unreadable",
            "unreadable front matter, line 4: nested mappings and multi-line values aren't supported; fix it by hand, "
            "orbit can't read the note",
        ),
        (
            "error",
            "Hans Müller",
            "clash",
            "its email address hans.mueller@acme-ag.example is also that of [[Hans Kopie]]; one must change",
        ),
        (
            "error",
            "Hans Müller",
            "clash",
            "its id per_01M4WNN540CGMAHYXV1R90AA5V is also that of [[Hans Kopie]]; one must change",
        ),
        (
            "error",
            "Odd",
            "schema",
            "type: unknown type 'gadget'; one of person, organization, interaction, task, topic, review",
        ),
        ("warning", "Hans Kopie", "name not the file's",
         "its name 'Hans Müller' isn't its file's: rename_entity to its name renames the file and the links to it; to "
         "the file's, it sets the name"),
        (
            "warning",
            "Loose",
            "no type",
            "in 02_Organizations, but not a note of orbit's: add `type: organization`, or move it",
        ),
        ("warning", "Hans Moved", "name not the file's",
         "its name 'Moved' isn't its file's: rename_entity to its name renames the file and the links to it; to the "
         "file's, it sets the name"),
        ("warning", "Hans Moved", "wrong folder", "a person belongs in 01_People"),
    ]  # fmt: skip


def test_fix_assigns_missing_ids_and_lowercases_addresses(crm):
    crm.vault.write("01_People/New.md", "---\ntype: person\nname: New\nemails:\n  - New@X.example\n---\n")
    edit(crm, "02_Organizations/Acme AG.md", "  - acme-ag.example", "  - Acme-AG.example")
    found = rules(lint(crm))
    assert found == [
        ("error", "New", "missing id", "no id; lint_vault with fix assigns one"),
        ("warning", "New", "not lower case", "emails: lint_vault with fix writes them in lower case"),
        ("warning", "Acme AG", "not lower case", "domains: lint_vault with fix writes them in lower case"),
    ]
    result = lint(crm, fix=True)
    assert [f["name"] for f in result["fixed"]] == ["New", "Acme AG"]
    assert result["issues"] == []
    assert lint(crm)["issues"] == []
    new = crm.vault.path("01_People/New.md").read_text(encoding="utf-8")
    assert new.startswith("---\ntype: person\nid: per_")
    assert "  - new@x.example\n" in new


def test_a_review_decided_same_is_merged_before_the_check(crm):
    edit(crm, "90_Review/2026-10-18 Duplicate – Hans and Hans Müller.md", "decision: pending", "decision: same")
    assert lint(crm)["issues"] == []
    assert not crm.vault.path("01_People/Hans.md").exists()
