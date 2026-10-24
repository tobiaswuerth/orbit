"""The lines orbit appends to a note: observations, and history lines that record a field's changes or why the note
was created. Each carries its date and its source; the index reads them back.

    - 2026-10-14 · Decides on the budget · «Das Budget für 2027 ist freigegeben.» · [[2026-10-14 Email – …]] · high
    - 2026-11-20 · job_title: Leiter Einkauf → Head of Procurement · [[2026-11-20 Email – …]]
    - 2026-10-14 · created: no candidate matched hans.mueller@acme-ag.example · [[2026-10-14 Email – …]]
"""

import re
from dataclasses import dataclass

SEP = " · "
ARROW = " → "
CONFIDENCE = ("high", "medium")
OBSERVATION = re.compile(r"- (\d{4}-\d{2}-\d{2}) · (.+?) · «(.*)» · (.+) · (high|medium)")
CHANGE = re.compile(r"- (\d{4}-\d{2}-\d{2}) · ([^\s:·]+): (.*) · (.+?)")
EMPTY = '""'  # the value of a field that was cleared


def text(value):
    """Text as one line that can't be taken for the separators: whitespace collapsed, « » as ‹ ›, " · " as ", ",
    " → " as " -> "."""
    value = re.sub(r"\s+", " ", value).strip().replace("«", "‹").replace("»", "›").replace(ARROW, " -> ")
    return value.replace(SEP.strip(), ",").replace(" ,", ",") if SEP.strip() in value else value


@dataclass(frozen=True)
class Observation:
    date: str
    statement: str
    evidence: str
    source: str
    confidence: str

    def line(self):
        return SEP.join(
            [f"- {self.date}", text(self.statement), f"«{text(self.evidence)}»", self.source, self.confidence]
        )

    @classmethod
    def parse(cls, line):
        """The observation a line holds, or None."""
        match = OBSERVATION.fullmatch(line.strip())
        return cls(*match.groups()) if match else None


@dataclass(frozen=True)
class Change:
    date: str
    field: str  # "created" for the line that says why the note was created
    old: str | None  # None if the field was empty before
    new: str | None  # None if the field was cleared; for "created", the reason
    source: str

    def line(self):
        new = EMPTY if self.new is None else self.new
        value = new if self.old is None else f"{self.old}{ARROW}{new}"
        return SEP.join([f"- {self.date}", f"{self.field}: {value}", self.source])

    @classmethod
    def parse(cls, line):
        """The change a line records, or None."""
        match = CHANGE.fullmatch(line.strip())
        if not match:
            return None
        date, field, value, source = match.groups()
        if field == "created":
            return cls(date, field, None, value, source)
        old, arrow, new = value.partition(ARROW)
        if not arrow:
            old, new = None, value
        return cls(date, field, old, None if new == EMPTY else new, source)
