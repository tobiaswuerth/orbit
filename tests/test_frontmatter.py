"""Front matter: orbit's strict reader and writer of flat YAML, checked against a full YAML parser."""

import datetime
import random

import pytest
import yaml

from orbit import frontmatter
from orbit.frontmatter import FrontMatterError

from .conftest import EXAMPLE


def full_yaml(text):
    """What a full YAML parser reads, with dates and times as the ISO strings orbit keeps them as."""

    def iso(value):
        if isinstance(value, list):
            return [iso(v) for v in value]
        if isinstance(value, datetime.date | datetime.datetime):
            return value.isoformat()
        return value

    return {key: iso(value) for key, value in (yaml.safe_load(text) or {}).items()}


# Values orbit writes: plain where YAML reads them back unchanged, quoted where it wouldn't.
CORPUS = [
    "Hans Müller",
    "anna.keller@acme-ag.example",
    "Industriestrasse 12, 8400 Winterthur",
    "bis am 1. November",
    "5bedd25b82fa9eb7a0b72d352acd9e390083efd9be6aa866591c6237ee117980",
    "per_01M3V0RPR04X2CSM8CEMSVTWVA",
    "O'Brien & Partner (Schweiz)",
    "AW: Offerte Wartungsvertrag 2027",
    "[[Acme AG]]",
    "+41 52 123 45 67",
    "<20261014093200.4711@acme-ag.example>",
    "mail/processed/2026/x.eml",
    "C:\\mail\\x.eml",
    'Say "hi"',
    "issue #12",
    "#hashtag",
    "- not a list",
    "key: value",
    "ends with colon:",
    " leading space",
    "trailing space ",
    "",
    "yes",
    "No",
    "on",
    "OFF",
    "y",
    "true",
    "False",
    "null",
    "~",
    "8400",
    "1.5",
    "1e5",
    "1e-5",
    "0x1F",
    "0o17",
    "1_000",
    "1.5.3",
    "12e",
    "2026-10-14",
    "2026-10-14T09:32:00+02:00",
    "2026-13-45",
    "2026-10-14 09:32:00",
    "line\nbreak",
    "tab\there",
    "nul\x00",
    "bell\x07 and del\x7f",
    "next line\x85",
    "\u2028separator",
    "«quoted»",
    "Café · Zürich – Genève",
    "emoji 🚀",
    "*star",
    "&anchor",
    "!tag",
    "|block",
    ">folded",
    "%directive",
    "@reserved",
    "`backtick",
    "?question",
    "{flow}",
    "_underscore",
]


@pytest.mark.parametrize("value", CORPUS)
def test_written_values_read_back_unchanged_by_both_parsers(value):
    text = frontmatter.dump({"key": value, "list": [value, "x"]})
    assert frontmatter.parse(text) == {"key": value, "list": [value, "x"]}
    assert full_yaml(text) == {"key": value, "list": [value, "x"]}


def test_random_strings_read_back_unchanged_by_both_parsers():
    alphabet = "aZ09 .,-_@()&'\"\\:#!?*|>%`[]{}+~=/ \t\nüé«»·–🚀\x00\x1f\x7f\x85\u2028\ufeff"
    rng = random.Random(7)
    for _ in range(3000):
        value = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 12)))
        text = frontmatter.dump({"key": value})
        assert frontmatter.parse(text) == {"key": value}, repr(value)
        assert full_yaml(text) == {"key": value}, repr(value)


def test_plain_values_stay_plain():
    text = frontmatter.dump(
        {
            "name": "Hans Müller",
            "date": "2026-10-14T09:32:00+02:00",
            "created": "2026-10-14",
            "me": True,
            "sha256": "5bedd25b82fa",
            "address": "Industriestrasse 12, 8400 Winterthur",
        }
    )
    assert text == (
        "name: Hans Müller\n"
        "date: 2026-10-14T09:32:00+02:00\n"
        "created: 2026-10-14\n"
        "me: true\n"
        "sha256: 5bedd25b82fa\n"
        "address: Industriestrasse 12, 8400 Winterthur\n"
    )


def test_quotes_what_yaml_would_read_otherwise():
    text = frontmatter.dump({"a": "[[Acme AG]]", "b": "8400", "c": "yes", "d": 'C:\\x "y"', "e": "a\nb"})
    assert text == 'a: "[[Acme AG]]"\nb: "8400"\nc: "yes"\nd: "C:\\\\x \\"y\\""\ne: "a\\nb"\n'


def test_lists_are_block_lists():
    assert frontmatter.dump({"emails": ["a@x.example", "b@x.example"], "none": [], "empty": None}) == (
        "emails:\n  - a@x.example\n  - b@x.example\nnone: []\nempty:\n"
    )


def test_list_items_may_be_empty():
    assert frontmatter.dump({"items": [None, "x"]}) == "items:\n  -\n  - x\n"
    assert frontmatter.parse("items:\n  -\n  - x\n") == {"items": [None, "x"]}


def test_a_key_with_trailing_spaces_still_takes_the_list_below():
    text = "items: \nnone:  \nmore: \n  - x\n"
    assert frontmatter.parse(text) == full_yaml(text) == {"items": None, "none": None, "more": ["x"]}


def test_a_list_item_of_only_a_comment_is_empty_as_in_yaml():
    text = "items:\n  - #tag\n  - x # note\n"
    assert frontmatter.parse(text) == full_yaml(text) == {"items": [None, "x"]}


def test_dump_refuses_keys_yaml_would_misread():
    with pytest.raises(ValueError, match="key"):
        frontmatter.dump({"a: b": "x"})


def test_dump_refuses_values_it_cannot_write():
    with pytest.raises(TypeError, match="int"):
        frontmatter.dump({"a": 1})


def test_reads_what_obsidian_writes():
    text = (
        "# a comment\n"
        "name: Hans Müller   # trailing comment\n"
        "single: 'it''s'\n"
        'double: "tab\\tand \\u00fc \\x41 \\U0001F680 \\/ \\N\\_\\L\\P\\e\\a\\b\\v\\f\\r\\0\\ "  # comment\n'
        "\n"
        "aliases:\n"
        "- Hansi\n"
        "\n"
        "  - Hansruedi\n"
        "tags: []\n"
        "empty:\n"
        "nothing: ~\n"
        "yes_: True\n"
        "no_: FALSE\n"
        "my prop: x\n"
    )
    assert frontmatter.parse(text) == {
        "name": "Hans Müller",
        "single": "it's",
        "double": "tab\tand ü A 🚀 / \x85\xa0\u2028\u2029\x1b\x07\x08\x0b\x0c\r\x00 ",
        "aliases": ["Hansi", "Hansruedi"],
        "tags": [],
        "empty": None,
        "nothing": None,
        "yes_": True,
        "no_": False,
        "my prop": "x",
    }


@pytest.mark.parametrize(
    "text, line, message",
    [
        ("org:\n  name: Acme\n", 2, "nested"),
        ("a: x\n  b\n", 2, "nested"),
        ("emails: [a@x.example]\n", 1, "block list"),
        ("org: {name: Acme}\n", 1, "block list"),
        ("notes: |\n  text\n", 1, "multi-line"),
        ("notes: >\n  text\n", 1, "multi-line"),
        ("a: &x 1\n", 1, "anchors"),
        ("a: *x\n", 1, "anchors"),
        ("a: !tag x\n", 1, "anchors"),
        ("a: %x\n", 1, "reserved"),
        ("a: @x\n", 1, "reserved"),
        ("a: `x\n", 1, "reserved"),
        ("a: - x\n", 1, "list"),
        ("a: ? x\n", 1, "quote"),
        ("subject: AW: Offerte\n", 1, "quote"),
        ("subject: ends:\n", 1, "quote"),
        ("a: x\na: y\n", 2, "twice"),
        ("- x\n", 1, "under a key"),
        ("a: x\n- y\n", 2, "under a key"),
        ('a: "open\n', 1, "closing"),
        ("a: 'open\n", 1, "closing"),
        ('a: "x" y\n', 1, "after the closing"),
        ("a: 'x' y\n", 1, "after the closing"),
        ('a: "\\q"\n', 1, "escape"),
        ('a: "\\x4"\n', 1, "escape"),
        ('a: "x\\', 1, "escape"),
        ("a:b\n", 1, "key: value"),
        ("'a': b\n", 1, "key: value"),
        ("\t- x\n", 1, "tab"),
        ("a:\n\t- x\n", 2, "tab"),
        ("a:\n  \t- x\n", 2, "tab"),
        ("org: [[Acme AG]]\n", 1, 'quote a wikilink, as in "\\[\\[Acme AG\\]\\]"'),
        ("related:\n  - [[Acme AG]]\n", 2, "quote a wikilink"),
        ("a:\n  - [x]\n", 2, "block list"),
        ("a:\n  - {b: c}\n", 2, "block list"),
        ("a:\n  - |\n", 2, "multi-line"),
        ("a:\n  - >\n", 2, "multi-line"),
    ],
)
def test_refuses_what_it_would_read_differently_from_yaml(text, line, message):
    with pytest.raises(FrontMatterError, match=message) as error:
        frontmatter.parse(text)
    assert error.value.line == line
    assert str(error.value).startswith(f"line {line}: ")


def test_line_numbers_count_from_a_given_line():
    with pytest.raises(FrontMatterError) as error:
        frontmatter.parse("a: x\nb: [1]\n", first_line=2)
    assert error.value.line == 3


def test_split_separates_front_matter_and_body():
    assert frontmatter.split("---\na: x\n---\n## Notes\n") == ("a: x\n", "## Notes\n")
    assert frontmatter.split("---\n---\n") == ("", "")
    assert frontmatter.split("\ufeff---\r\na: x\r\n---\r\nbody\r\n") == ("a: x\n", "body\n")
    assert frontmatter.split("---\na: x\n---") == ("a: x\n", "")


def test_split_without_front_matter():
    assert frontmatter.split("# Title\n") == (None, "# Title\n")
    assert frontmatter.split("") == (None, "")
    assert frontmatter.split("----\n") == (None, "----\n")


def test_split_refuses_unclosed_front_matter():
    with pytest.raises(FrontMatterError, match="closing ---") as error:
        frontmatter.split("---\na: x\n")
    assert error.value.line == 1


def test_read_and_render():
    fields, body = frontmatter.read("---\na: x\n---\nbody\n")
    assert (fields, body) == ({"a": "x"}, "body\n")
    assert frontmatter.render(fields, body) == "---\na: x\n---\nbody\n"
    assert frontmatter.read("body\n") == (None, "body\n")
    assert frontmatter.render(None, "body\n") == "body\n"


def test_read_reports_lines_of_the_file():
    with pytest.raises(FrontMatterError) as error:
        frontmatter.read("---\na: x\nb: [1]\n---\n")
    assert error.value.line == 3


@pytest.mark.parametrize("path", sorted(EXAMPLE.rglob("*.md")), ids=lambda p: p.name)
def test_example_notes_round_trip_byte_for_byte(path):
    text = path.read_text(encoding="utf-8")
    fields, body = frontmatter.read(text)
    if fields is not None:
        fm, _ = frontmatter.split(text)
        assert fields == full_yaml(fm)
    assert frontmatter.render(fields, body) == text
