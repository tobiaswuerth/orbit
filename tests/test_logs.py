"""Each run of `orbit serve` keeps what it said in a log file of its own."""

import datetime
import logging

from orbit import console, logs

NOW = datetime.datetime(2026, 10, 23, 21, 5, 9)


def test_a_run_logs_to_a_file_of_its_own(home):
    path = logs.start("serve", NOW)
    try:
        console.say("orbit: D:\\vault, index up to date")
        logging.getLogger("uvicorn.access").propagate = False  # as uvicorn configures it
        logs.attach("uvicorn.access")
        logging.getLogger("uvicorn.access").info('127.0.0.1 - "POST /mcp/write HTTP/1.1" 200')
        logging.getLogger("orbit.server").error("tool failed")
    finally:
        logs.stop()
    assert path == home / "logs" / "serve-2026-10-23_210509.log"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert [line.split(" ", 2)[2] for line in lines] == [
        "INFO orbit: orbit: D:\\vault, index up to date",
        'INFO uvicorn.access: 127.0.0.1 - "POST /mcp/write HTTP/1.1" 200',
        "ERROR orbit.server: tool failed",
    ]
    console.say("after the run")  # no file any more
    assert "after the run" not in path.read_text(encoding="utf-8")


def test_two_runs_in_one_second_get_two_files(home):
    first = logs.start("serve", NOW)
    logs.stop()
    logging.getLogger().setLevel(logging.DEBUG)  # a host that logs more keeps doing so
    second = logs.start("serve", NOW)
    assert logging.getLogger().level == logging.DEBUG
    logs.stop()
    logs.stop()  # stopped already: nothing to do
    logging.getLogger().setLevel(logging.WARNING)
    assert (first.name, second.name) == ("serve-2026-10-23_210509.log", "serve-2026-10-23_210509-2.log")


def test_every_log_is_kept(home):
    folder = home / "logs"
    folder.mkdir(parents=True)
    older = [f"serve-2026-10-0{day}_120000.log" for day in range(1, 10)]
    for name in older:
        (folder / name).write_text("x", encoding="utf-8")
    logs.start("serve", NOW)
    logs.stop()
    assert sorted(p.name for p in folder.iterdir()) == [*older, "serve-2026-10-23_210509.log"]
