"""Note bodies: `## ` sections that orbit appends to or replaces, leaving every other byte as it was."""

import random

import pytest

from orbit.sections import Body, build, text_lines

from .conftest import EXAMPLE

PERSON = ("Notes", "Observations", "Documents", "History")


@pytest.mark.parametrize(
    "text",
    [
        "",
        "\n",
        "## Notes\n",
        "## Notes",
        "intro\n\n## Notes\nmine\n\n\n## History\n- a\n",
        "## Notes\n```\n## not a heading\n```\n~~~\n## nor this\n~~~\n## History\n",
        "no headings at all\n",
        "## Notes\r\n",
    ],
)
def test_parsing_and_rendering_gives_back_the_text(text):
    assert Body.parse(text).text() == text


def test_random_bodies_come_back_unchanged():
    pieces = ["## Notes", "## History", "text", "", "```", "- item", "### Sub", "##No space", "  ## indented"]
    rng = random.Random(3)
    for _ in range(500):
        text = "\n".join(rng.choice(pieces) for _ in range(rng.randint(0, 8)))
        assert Body.parse(text).text() == text


def test_headings_skip_fenced_code():
    body = Body.parse("## Notes\n```\n## Fake\n```\n## History\n- a\n")
    assert body.headings() == ["Notes", "History"]
    assert body.lines("Notes") == ["```", "## Fake", "```"]


def test_lines_leave_out_trailing_blank_lines():
    body = Body.parse("## Notes\n\n## Observations\n- a\n- b\n\n\n## History\n")
    assert body.lines("Notes") == []
    assert body.lines("Observations") == ["- a", "- b"]
    assert body.lines("Missing") is None


def test_append_adds_after_the_last_line_of_the_section():
    body = Body.parse("## Notes\nmine\n\n## History\n- a\n\n")
    body.append("History", ["- b"], PERSON)
    assert body.text() == "## Notes\nmine\n\n## History\n- a\n- b\n\n"


def test_append_to_an_empty_section():
    body = Body.parse("## Observations\n\n## History\n")
    body.append("Observations", ["- a"], PERSON)
    assert body.text() == "## Observations\n- a\n\n## History\n"


def test_append_to_a_text_without_final_newline():
    body = Body.parse("## History\n- a")
    body.append("History", ["- b"], PERSON)
    assert body.text() == "## History\n- a\n- b\n"


def test_append_creates_a_missing_section_in_order():
    body = Body.parse("## Notes\n\n## History\n- a\n")
    body.append("Observations", ["- o"], PERSON)
    assert body.text() == "## Notes\n\n## Observations\n- o\n\n## History\n- a\n"


def test_append_creates_a_missing_section_at_the_end():
    body = Body.parse("## Notes\n")
    body.append("History", ["- a"], PERSON)
    assert body.text() == "## Notes\n\n## History\n- a\n"
    body = Body.parse("## Notes\nmine")
    body.append("History", ["- a"], PERSON)
    assert body.text() == "## Notes\nmine\n\n## History\n- a\n"


def test_append_creates_the_first_section():
    body = Body.parse("")
    body.append("History", ["- a"], PERSON)
    assert body.text() == "## History\n- a\n"
    body = Body.parse("intro\n")
    body.append("History", ["- a"], PERSON)
    assert body.text() == "intro\n\n## History\n- a\n"


def test_sections_outside_the_order_go_last():
    body = Body.parse("## History\n- a\n")
    body.append("Elsewhere", ["x"], PERSON)
    assert body.text() == "## History\n- a\n\n## Elsewhere\nx\n"


def test_replace_sets_the_content_and_keeps_the_rest():
    body = Body.parse("## Summary\nold\nolder\n\n## Key quote\n> q\n")
    body.replace("Summary", ["new"], ("Summary", "Key quote"))
    assert body.text() == "## Summary\nnew\n\n## Key quote\n> q\n"
    body.replace("Key quote", ["> r"], ("Summary", "Key quote"))
    assert body.text() == "## Summary\nnew\n\n## Key quote\n> r\n"


def test_replace_creates_a_missing_section():
    body = Body.parse("## Summary\ntext\n")
    body.replace("Decisions", ["- d"], ("Summary", "Decisions"))
    assert body.text() == "## Summary\ntext\n\n## Decisions\n- d\n"


def test_build_writes_sections_as_orbit_does():
    assert build([("Notes", []), ("History", ["- a"])]) == "## Notes\n\n## History\n- a\n"
    assert build([("Notes", [])]) == "## Notes\n"
    assert build([]) == ""


@pytest.mark.parametrize("path", sorted(EXAMPLE.rglob("*.md")), ids=lambda p: p.name)
def test_example_bodies_are_built_as_orbit_builds_them(path):
    text = path.read_text(encoding="utf-8")
    body = text.split("---\n", 2)[2] if text.startswith("---\n") else text
    parsed = Body.parse(body)
    if parsed.headings():
        assert build([(h, parsed.lines(h)) for h in parsed.headings()]) == body


def test_text_lines_escape_only_what_would_open_a_heading_or_a_fence():
    text = "#tag stays a tag\n# Heading\n### Deeper\n#\n~~~\n```py\n    # indented code\nplain"
    assert text_lines(text) == [
        "#tag stays a tag",
        r"\# Heading",
        r"\### Deeper",
        r"\#",
        r"\~~~",
        r"\```py",
        "    # indented code",
        "plain",
    ]
