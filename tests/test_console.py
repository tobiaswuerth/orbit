"""What orbit tells the user goes to stderr, so stdout stays for results."""

from orbit import console


def test_say_writes_to_stderr(capsys):
    console.say("indexed", 3)
    assert capsys.readouterr() == ("", "indexed 3\n")


def test_count():
    assert [console.count(n, "note") for n in (0, 1, 12345)] == ["0 notes", "1 note", "12,345 notes"]


def test_an():
    assert [console.an(n) for n in ("person", "organization", "interaction")] == [
        "a person",
        "an organization",
        "an interaction",
    ]
