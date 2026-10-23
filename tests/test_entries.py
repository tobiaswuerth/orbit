"""Observation and history lines: written with their date and source, and read back."""

import pytest

from orbit.entries import Change, Observation
from orbit.sections import Body

from .conftest import EXAMPLE

SOURCE = "[[2026-10-14 Email – AW Offerte Wartungsvertrag 2027]]"


def test_observations_read_back():
    observation = Observation("2026-10-14", "Decides on the budget", "Das Budget ist freigegeben.", SOURCE, "medium")
    assert (
        observation.line()
        == f"- 2026-10-14 · Decides on the budget · «Das Budget ist freigegeben.» · {SOURCE} · medium"
    )
    assert Observation.parse(observation.line()) == observation


def test_observation_text_keeps_to_one_line_without_separators():
    observation = Observation("2026-10-14", "Said «no» · twice\nloudly", "«Nein» · «nein»", "Tobias in chat", "high")
    assert observation.line() == "- 2026-10-14 · Said ‹no›, twice loudly · «‹Nein›, ‹nein›» · Tobias in chat · high"
    assert Observation.parse(observation.line()).statement == "Said ‹no›, twice loudly"


@pytest.mark.parametrize(
    "change, line",
    [
        (
            Change("2026-11-20", "job_title", "Leiter Einkauf", "Head of Procurement", SOURCE),
            f"- 2026-11-20 · job_title: Leiter Einkauf → Head of Procurement · {SOURCE}",
        ),
        (
            Change("2026-11-20", "job_title", None, "Leiter Einkauf", SOURCE),
            f"- 2026-11-20 · job_title: Leiter Einkauf · {SOURCE}",
        ),
        (
            Change("2026-11-20", "job_title", "Leiter Einkauf", None, SOURCE),
            f'- 2026-11-20 · job_title: Leiter Einkauf → "" · {SOURCE}',
        ),
        (
            Change("2026-10-14", "created", None, "no candidate matched a → b", SOURCE),
            f"- 2026-10-14 · created: no candidate matched a → b · {SOURCE}",
        ),
        (
            Change("2026-11-20", "org", "[[Acme AG]]", "[[Beta GmbH]]", "Tobias in chat, 2026-11-20"),
            "- 2026-11-20 · org: [[Acme AG]] → [[Beta GmbH]] · Tobias in chat, 2026-11-20",
        ),
    ],
)
def test_changes_read_back(change, line):
    assert change.line() == line
    assert Change.parse(line) == change


@pytest.mark.parametrize("line", ["", "- 2026-10-14 · nothing to see", "- yesterday · job_title: x · [[s]]", "text"])
def test_other_lines_are_neither(line):
    assert Observation.parse(line) is None
    assert Change.parse(line) is None


def test_the_examples_lines():
    body = Body.parse((EXAMPLE / "01_People" / "Hans Müller.md").read_text(encoding="utf-8").split("---\n", 2)[2])
    observations = [Observation.parse(line) for line in body.lines("Observations")]
    assert [o.confidence for o in observations] == ["high", "medium"]
    assert observations[0].evidence == "Lieber Tobias"
    (created,) = [Change.parse(line) for line in body.lines("History")]
    assert created == Change("2026-10-14", "created", None, "no candidate matched hans.mueller@acme-ag.example", SOURCE)
