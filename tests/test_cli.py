"""The `orbit` command: init, reindex and status; results on stdout, everything else on stderr."""

import json

import pytest
from filelock import FileLock

from orbit import cli, index
from orbit.crm import Crm


def run(capsys, *argv):
    code = cli.main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, out, err


def test_help_names_every_command(capsys):
    code, out, _ = run(capsys)
    assert code == 0
    for command in ("init", "reindex", "status"):
        assert command in out


def test_unknown_arguments_fail(capsys):
    assert run(capsys, "status", "--colour")[0] == 2


def test_init_creates_a_vault(tmp_path, capsys):
    code, out, err = run(capsys, "init", tmp_path / "crm", "--name", "Tobias", "--email", "tobias@meinefirma.example")
    assert code == 0
    assert out.splitlines()[0] == "created 01_People/"
    assert "created 01_People/Me.md" in out
    assert err == ""
    code, out, err = run(capsys, "init", tmp_path / "crm")
    assert (code, out) == (0, "")
    assert "is a vault already" in err


def test_init_without_an_address_says_to_add_one(tmp_path, capsys):
    # Without one, orbit takes the owner's own address for someone it doesn't know, in every mail.
    code, _, err = run(capsys, "init", tmp_path / "crm", "--name", "Tobias")
    assert code == 0
    assert err == (
        "01_People/Me.md has no email address, so orbit can't tell mail from and to you: add yours to its emails\n"
    )


def test_init_of_a_vault_with_a_me_says_its_name_and_addresses_stay(tmp_path, capsys):
    run(capsys, "init", tmp_path / "crm", "--email", "tobias@meinefirma.example")
    code, out, err = run(capsys, "init", tmp_path / "crm", "--name", "Tobias", "--email", "tobias@privat.example")
    assert (code, out) == (0, "")
    assert "01_People/Me.md exists already, so --name and --email changed nothing: edit it instead" in err


def test_a_vault_under_the_home_folder_written_with_a_tilde(tmp_path, capsys, monkeypatch):
    # PowerShell and cmd pass "~/crm" on as it is, as the README writes it.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert run(capsys, "init", "~/crm")[0] == 0
    assert (tmp_path / "crm" / "99_System" / "orbit.toml").is_file()
    assert not (tmp_path / "~").exists()
    assert run(capsys, "status", "~/crm")[0] == 0


def test_init_refuses_a_bad_address(tmp_path, capsys):
    code, _, err = run(capsys, "init", tmp_path / "crm", "--email", "nobody")
    assert code == 1
    assert err == "orbit: emails: 'nobody' is not an email address\n"


def test_reindex(example, capsys):
    code, out, _ = run(capsys, "reindex", example)
    assert code == 0
    assert out == ("indexed 11 notes: 4 people, 1 organization, 2 interactions, 2 tasks, 1 topic, 1 review\n")


def test_status(example, capsys):
    (example / "Inbox.md").write_text("loose", encoding="utf-8")
    code, out, _ = run(capsys, "status", example)
    assert code == 0
    lines = out.splitlines()
    assert lines[0] == f"vault: {example}"
    assert lines[1].startswith("index: ")
    assert "running" not in lines[1]
    assert lines[2:] == [
        "notes: 12 notes: 4 people, 1 organization, 2 interactions, 2 tasks, 1 topic, 1 review, 1 other",
        "pending reviews: 1",
        "clashes: 0, unreadable notes: 0",
    ]


def test_status_as_json(example, capsys):
    code, out, _ = run(capsys, "status", example, "--json")
    state = json.loads(out)
    assert (code, state["serving"], state["pending_reviews"], state["notes"]["person"]) == (0, False, 1, 4)


def test_status_while_orbit_runs_reads_its_index(example, home, capsys):
    with Crm(example, home) as crm:
        crm.refresh()
        code, out, _ = run(capsys, "status", example, "--json")
        assert (code, json.loads(out)["serving"], json.loads(out)["notes"]["task"]) == (0, True, 2)
        code, out, _ = run(capsys, "status", example)
        assert "(kept up to date by a running orbit)" in out


def test_status_of_a_running_orbit_without_an_index_yet(example, home, capsys):
    lock = FileLock(index.location(example, home).with_suffix(".lock"), timeout=0)
    with lock:
        code, _, err = run(capsys, "status", example)
    assert code == 1
    assert "another orbit process is using" in err


def test_commands_on_something_that_is_no_vault(tmp_path, capsys):
    for command in ("reindex", "status"):
        code, _, err = run(capsys, command, tmp_path)
        assert code == 1
        assert "is not an orbit vault" in err


def test_reindex_refuses_while_orbit_runs(example, home, capsys):
    with Crm(example, home):
        code, _, err = run(capsys, "reindex", example)
    assert code == 1
    assert "another orbit process is using" in err


@pytest.mark.parametrize("counts, text", [({}, "0 notes"), ({"person": 1}, "1 note: 1 person")])
def test_note_counts(counts, text):
    assert cli._notes(counts) == text


def test_lint(example, capsys):
    code, out, err = run(capsys, "lint", example)
    assert (code, out, err) == (0, "", "0 errors, 0 warnings\n")
    note = example / "01_People" / "Anna Keller.md"
    note.write_text(note.read_text(encoding="utf-8").replace("context: professional", "context: work"), "utf-8")
    (example / "01_People" / "New.md").write_text("---\ntype: person\nname: New\n---\n", encoding="utf-8")
    code, out, err = run(capsys, "lint", example)
    assert code == 1
    assert out.splitlines() == [
        "error: 01_People/Anna Keller.md: context: 'work' is not one of professional, personal, both",
        "error: 01_People/New.md: no id; lint_vault with fix assigns one",
    ]
    assert err == "2 errors, 0 warnings\n"
    code, out, _ = run(capsys, "lint", example, "--fix")
    assert code == 1
    assert out.splitlines()[0] == "fixed: 01_People/New.md"
    code, out, _ = run(capsys, "lint", example, "--json")
    assert (code, json.loads(out)["counts"]) == (1, {"error": 1, "warning": 0})


def test_serve(example, capsys, monkeypatch):
    calls = []
    monkeypatch.setattr(cli.server, "serve", lambda *args: calls.append(args))
    assert run(capsys, "serve", example, "--stdio")[0] == 0
    assert run(capsys, "serve", example, "--host", "0.0.0.0", "--port", "9000")[0] == 0
    assert run(capsys, "serve", example, "--tools", "read, write")[0] == 0
    assert calls == [
        (example, None, None, True, None),
        (example, "0.0.0.0", 9000, False, None),
        (example, None, None, False, ["read", "write"]),
    ]


def test_serve_refuses_tools_it_doesnt_have(example, capsys):
    code, _, err = run(capsys, "serve", example, "--tools", "read,delete")
    assert (code, err) == (1, "orbit: --tools: 'delete' is neither a group (read, write, upkeep) nor a tool\n")


@pytest.mark.parametrize("port", ["0", "70000", "-1"])
def test_serve_refuses_a_port_that_isnt_one(example, capsys, monkeypatch, port):
    monkeypatch.setattr(cli.server, "serve", lambda *args: pytest.fail("served"))
    code, _, err = run(capsys, "serve", example, "--port", port)
    assert code == 2
    assert "--port: a port number, 1 to 65535" in err


def test_init_says_it_writes_the_bases(capsys):
    code, out, _ = run(capsys, "init", "--help")
    assert (code, "Bases views" in out) == (0, True)


def test_a_file_system_error_is_one_line_not_a_traceback(example, capsys, monkeypatch):
    error = PermissionError(13, "Permission denied", str(example / "01_People"))

    def denied(*args, **kwargs):
        raise error

    monkeypatch.setattr(cli.vault, "init", denied)
    code, _, err = run(capsys, "init", example)
    assert code == 1
    assert err == f"orbit: {error}\n"
    assert err.startswith("orbit: [Errno 13] Permission denied: ")


def test_stopping_with_ctrl_c_is_quiet(example, capsys, monkeypatch):
    def interrupted(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.server, "serve", interrupted)
    assert run(capsys, "serve", example, "--stdio") == (130, "", "")


OPEN_TASK = "04_Tasks/Send revised offer for Wartungsvertrag 2027.md"
WAITING_TASK = "04_Tasks/Anna Keller to follow up on the technical clarification.md"
TASKS = ("Anna Keller to follow up on the technical clarification", "Send revised offer for Wartungsvertrag 2027")


def test_close_tasks_cancels_the_open_and_waiting_tasks_from_before_a_date(example, capsys):
    code, out, _ = run(capsys, "close-tasks", example, "--before", "2026-10-15", "--dry-run")
    assert (code, out.splitlines()) == (0, [f"would cancel: {t}" for t in TASKS])
    assert "status: open" in (example / OPEN_TASK).read_text(encoding="utf-8")
    code, out, err = run(capsys, "close-tasks", example, "--before", "2026-10-15")
    assert (code, out.splitlines()) == (0, [f"cancelled: {t}" for t in TASKS])
    assert all("status: cancelled" in (example / p).read_text(encoding="utf-8") for p in (OPEN_TASK, WAITING_TASK))
    assert "2 tasks cancelled" in err


def test_close_tasks_dates_a_task_by_the_interaction_it_came_from(example, capsys):
    code, out, err = run(capsys, "close-tasks", example, "--before", "2026-10-14")  # the email's own day
    assert (code, out) == (0, "")
    assert "no open or waiting tasks from before 2026-10-14" in err


def test_close_tasks_ticks_the_boxes_for_the_server_that_holds_the_vault(example, home, capsys):
    with Crm(example, home) as crm:  # holds the vault, as orbit serve does
        crm.refresh()
        assert run(capsys, "close-tasks", example, "--before", "2026-10-15", "--dry-run")[1].splitlines() == [
            f"would cancel: {t}" for t in TASKS
        ]
        assert "cancel: true" not in (example / OPEN_TASK).read_text(encoding="utf-8")
        code, out, err = run(capsys, "close-tasks", example, "--before", "2026-10-15")
        assert (code, out.splitlines()) == (0, [f"ticked Cancel: {t}" for t in TASKS])
        assert "orbit serve cancels them as it notices" in err
        crm.refresh({OPEN_TASK, WAITING_TASK})  # what the server's watcher does
        assert all("status: cancelled" in (example / p).read_text(encoding="utf-8") for p in (OPEN_TASK, WAITING_TASK))


def test_close_tasks_wants_a_date(example, capsys):
    assert run(capsys, "close-tasks", example)[0] == 2
    code, _, err = run(capsys, "close-tasks", example, "--before", "15.10.2026")
    assert code == 2
    assert "--before: a date, YYYY-MM-DD" in err
