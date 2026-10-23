"""Changes to a note's fields that every write tool makes the same way: adding to a list, and setting a single value
with a history line, so that orbit can later tell whether a value is newer than the one stored."""

from . import names, schema
from .entries import Change


class Changes(list):
    """The notes a tool created or changed, each once, as `Crm.save` describes them."""

    def add(self, change):
        if change and all(c["path"] != change["path"] for c in self):
            self.append(change)
        return change


def same(a, b):
    """Whether two values are the same, in any case, taking a link and the name of the note it leads to as the same:
    "[[Acme AG]]" and "acme ag"."""
    key = lambda v: names.file_key(schema.link_target(v) or v) if isinstance(v, str) else v  # noqa: E731
    return key(a) == key(b)


def listed(value):
    return value if isinstance(value, list) else [] if value is None else [value]


def add_items(note, field, items):
    """Add items to a list field, leaving out those it holds already. The items added."""
    current = listed(note.fields.get(field))
    added = []
    for item in items:
        if not any(same(item, c) for c in current + added):
            added.append(item)
    if added:
        note.fields[field] = current + added
    return added


def remove_items(note, field, items, source, date):
    """Take items out of a list field, each with a line in the history. The items taken out, as they were."""
    current = listed(note.fields.get(field))
    gone = [c for c in current if any(same(c, i) for i in items)]
    if not gone:
        return []
    kept = [c for c in current if c not in gone]
    if kept:
        note.fields[field] = kept
    else:
        note.fields.pop(field, None)
    lines = [Change(date, field, str(item), None, source).line() for item in gone]
    note.body.append("History", lines, schema.TYPES[note.type].sections)
    return gone


def set_value(note, field, value, source, date, history=True):
    """Set a single-value field (None clears it), and, on people, organizations and topics, write a history line
    dated `date`, the day the source says it. The Change, or None if the field held the value already."""
    old = note.fields.get(field)
    if same(old, value) or (old in (None, "") and value is None):
        return None
    if value is None:
        note.fields.pop(field)
    else:
        note.fields[field] = value
    change = Change(date, field, None if old in (None, "") else str(old), value, source)
    if history and note.type in schema.ENTITY:
        note.body.append("History", [change.line()], schema.TYPES[note.type].sections)
    return change
