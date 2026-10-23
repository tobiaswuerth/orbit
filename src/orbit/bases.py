"""The Obsidian Bases views `orbit init` writes to 95_Bases: People, Follow-ups and Review. Each is a .base file, YAML
in Obsidian's Bases syntax: tables over the notes' front matter, which Obsidian shows and lets the owner edit in
place. orbit writes a view only where none is, so the owner's changes stay."""

from importlib.resources import files

FOLDER = "95_Bases"
NAMES = ("People.base", "Follow-ups.base", "Review.base")


def templates():
    """{file name: text} of the views."""
    return {name: (files(__package__) / "templates" / name).read_text(encoding="utf-8") for name in NAMES}
