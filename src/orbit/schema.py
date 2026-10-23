"""The note types orbit knows: their fields in the order they are written, their sections, and the rules their
values keep. `problems` checks a note's front matter; `clean` checks and normalizes a value a caller gives."""

import datetime
import re
from dataclasses import dataclass

from . import ids, names
from .errors import OrbitError

LINK = re.compile(r"\[\[([^\[\]|#^]+)(?:[#^|][^\[\]]*)?\]\]")
DOCUMENT = re.compile(r"\[([^\[\]]+)\]\((<[^<>]+>|[^\s()<>]+)\)")
UID = re.compile(r"CHE-\d{3}\.\d{3}\.\d{3}")
SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class Field:
    name: str
    kind: str = "text"  # text, date, datetime, bool, choice, link, ref (a link or text), email, domain, uid, sha256,
    # document ("[title](reference)"), id or type
    many: bool = False  # a list
    choices: tuple[str, ...] = ()
    to: tuple[str, ...] = ()  # the types a link may lead to; any if empty
    managed: bool = False  # set by orbit itself: callers can't set it


@dataclass(frozen=True)
class NoteType:
    name: str
    prefix: str  # of its ids
    folder: str
    fields: tuple[Field, ...]
    sections: tuple[str, ...]  # its body's sections, in order
    required: tuple[str, ...] = ()

    def field(self, name):
        return next((f for f in self.fields if f.name == name), None)

    @property
    def names(self):
        return tuple(f.name for f in self.fields)


class SchemaError(OrbitError):
    pass


def _common(*fields, dated=True):
    head = (Field("type", "type", managed=True), Field("id", "id", managed=True))
    tail = (Field("created", "date", managed=True),) + ((Field("updated", "date", managed=True),) if dated else ())
    return head + fields + tail


PERSON, ORGANIZATION, INTERACTION, TASK, TOPIC, REVIEW = (
    "person",
    "organization",
    "interaction",
    "task",
    "topic",
    "review",
)
ENTITY = (PERSON, ORGANIZATION, TOPIC)  # the types that hold observations and history
_people, _orgs = (PERSON,), (ORGANIZATION,)
_documents = Field("documents", "document", many=True, managed=True)

TYPES = {
    t.name: t
    for t in [
        NoteType(
            PERSON,
            "per",
            "01_People",
            _common(
                Field("name"),
                Field("me", "bool", managed=True),
                Field("aliases", many=True),
                Field("emails", "email", many=True),
                Field("phones", many=True),
                Field("org", "link", to=_orgs),
                Field("job_title"),
                Field("department"),
                Field("former_orgs", "link", many=True, to=_orgs),
                Field("reports_to", "link", to=_people),
                Field("assistant_of", "link", to=_people),
                Field("colleague_of", "link", many=True, to=_people),
                Field("introduced_by", "link", to=_people),
                Field("context", "choice", choices=("professional", "personal", "both")),
                Field("languages", many=True),
                Field("salutation", "choice", choices=("du", "Sie")),
                Field("location"),
                Field("last_contact", "date", managed=True),
                Field("next_followup", "date"),
                Field("review_status", "choice", choices=("confirmed", "needs_review")),
                Field("merged_from", "id", many=True, managed=True),
                Field("distinct_from", "link", many=True, to=_people, managed=True),
                _documents,
            ),
            ("Notes", "Observations", "Documents", "History"),
            ("name",),
        ),
        NoteType(
            ORGANIZATION,
            "org",
            "02_Organizations",
            _common(
                Field("name"),
                Field("aliases", many=True),
                Field("domains", "domain", many=True),
                Field("uid_che", "uid"),
                Field("industry"),
                Field("location"),
                Field("address"),
                Field("website"),
                Field("parent", "link", to=_orgs),
                Field(
                    "relationship",
                    "choice",
                    choices=("client", "prospect", "partner", "vendor", "employer", "personal"),
                ),
                Field("merged_from", "id", many=True, managed=True),
                Field("distinct_from", "link", many=True, to=_orgs, managed=True),
                _documents,
            ),
            ("Notes", "Observations", "Documents", "History"),
            ("name",),
        ),
        NoteType(
            INTERACTION,
            "int",
            "03_Interactions",
            _common(
                Field("kind", "choice", choices=("email", "meeting", "call", "message", "note", "automated")),
                Field("date", "datetime"),
                Field("direction", "choice", choices=("inbound", "outbound")),
                Field("subject"),
                Field("from", "link", to=_people),
                Field("to", "link", many=True, to=_people),
                Field("cc", "link", many=True, to=_people),
                Field("participants", "link", many=True, to=_people),
                Field("mentioned", "link", many=True, to=_people),
                Field("orgs", "link", many=True, to=_orgs),
                Field("topics", "link", many=True, to=(TOPIC,)),
                Field("language"),
                Field("message_id"),
                Field("in_reply_to"),
                Field("replies_to", "link", to=(INTERACTION,), managed=True),  # the interaction it answers
                Field("thread"),
                Field("source_file"),
                Field("sha256", "sha256"),
                _documents,
                dated=False,
            ),
            ("Summary", "Decisions", "Action items", "Key quote", "Documents", "Original"),
            ("kind", "date"),
        ),
        NoteType(
            TASK,
            "tsk",
            "04_Tasks",
            _common(
                Field("status", "choice", choices=("open", "waiting", "done", "cancelled")),
                Field("due", "date"),
                Field("due_note"),
                Field("owner", "link", to=(PERSON, ORGANIZATION)),  # an organization owes refunds, fixes, answers
                Field("related", "link", many=True),
                Field("origin", "link"),
            ),
            ("Details", "Notes"),
            ("status",),
        ),
        NoteType(
            TOPIC,
            "top",
            "05_Topics",
            _common(
                Field("name"),
                Field("aliases", many=True),
                Field("status", "choice", choices=("active", "paused", "closed")),
                Field("orgs", "link", many=True, to=_orgs),
                Field("people", "link", many=True, to=_people),
                _documents,
                Field("merged_from", "id", many=True, managed=True),
                Field("distinct_from", "link", many=True, to=(TOPIC,), managed=True),
            ),
            ("Notes", "Observations", "Documents", "History"),
            ("name",),
        ),
        NoteType(
            REVIEW,
            "rev",
            "90_Review",
            _common(
                Field("kind", "choice", choices=("duplicate", "job_change", "address", "other", "question")),
                Field("question"),
                Field("candidates", "link", many=True),
                Field("address", "email"),
                Field("decision", "choice", choices=("pending", "same", "different", "yes", "no", "answered")),
                Field("answer_yes", "bool"),  # boxes to tick in the Review base, one click each
                Field("answer_no", "bool"),
                Field("answer"),  # an open question's, in the owner's words
                Field("applied", "date", managed=True),
                Field("source", "ref"),
                dated=False,
            ),
            ("Evidence for", "Evidence against", "How to answer", "Applied"),
            ("kind", "question", "candidates", "decision"),
        ),
    ]
}
PREFIXES = {t.prefix: t.name for t in TYPES.values()}


def link(name):
    return f"[[{name}]]"


def link_target(value):
    """The note a wikilink leads to, without heading, block or display text; None if the value isn't a link."""
    match = LINK.fullmatch(value) if isinstance(value, str) else None
    return match[1].strip() if match else None


def order(type_name, fields):
    """Fields in the order notes of the type write them; fields outside the schema follow, in their own order."""
    known = TYPES[type_name].names
    return {k: fields[k] for k in known if k in fields} | {k: v for k, v in fields.items() if k not in known}


def unknown(type_name, fields):
    """The fields outside a type's schema."""
    return [k for k in fields if not TYPES[type_name].field(k)]


def problems(fields):
    """What breaks the schema in a note's front matter, as (field, message) pairs; fields outside the schema aren't
    problems (see `unknown`). The type must be known for anything else to be checked."""
    kind = fields.get("type")
    if kind not in TYPES:
        return [("type", f"unknown type {kind!r}; one of {', '.join(TYPES)}" if kind else "no type")]
    spec, found = TYPES[kind], []
    if not ids.is_valid(fields.get("id"), spec.prefix):
        found.append(("id", f"no valid id: {spec.prefix}_ and a ULID" if fields.get("id") else "no id"))
    found += [(name, "missing") for name in spec.required if fields.get(name) in (None, [], "")]
    for field in spec.fields[2:]:
        value = fields.get(field.name)
        if value is None:
            continue
        if field.many != isinstance(value, list):
            found.append((field.name, "should be a list" if field.many else "should be a single value"))
            continue
        for item in value if field.many else [value]:
            if item is not None and (message := _invalid(field, item)):
                found.append((field.name, message))
    return found


def _invalid(field, value):
    """Why a value breaks its field's rules, or None."""
    if field.kind == "bool":
        return None if isinstance(value, bool) else "should be true or false"
    if not isinstance(value, str):
        return "should be text"
    if field.kind == "choice" and value not in field.choices:
        return f"{value!r} is not one of {', '.join(field.choices)}"
    if field.kind == "date" and not is_date(value):
        return f"{value!r} is not a date (YYYY-MM-DD)"
    if field.kind == "datetime" and not (is_date(value) or _datetime(value)):
        return f"{value!r} is not a date or an ISO 8601 time with offset"
    if field.kind == "link" and not link_target(value):
        return f'{value!r} is not a wikilink, e.g. "[[Acme AG]]"'
    checks = {
        "email": (names.is_email, "an email address"),
        "domain": (names.is_domain, "a domain"),
        "uid": (UID.fullmatch, "a Swiss company UID (CHE-123.456.789)"),
        "sha256": (SHA256.fullmatch, "a SHA-256 hash in hex"),
        "document": (DOCUMENT.fullmatch, 'a document as "[title](reference)"'),
        "id": (ids.is_valid, "an id"),
    }
    if field.kind in checks and not checks[field.kind][0](value):
        return f"{value!r} is not {checks[field.kind][1]}"
    return None


def is_date(value):
    """Whether a value is a valid date, YYYY-MM-DD."""
    try:
        return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)) and bool(datetime.date.fromisoformat(value))
    except ValueError:
        return False


def _datetime(value):
    try:
        time = datetime.datetime.fromisoformat(value)
    except ValueError:
        return None
    return time if "T" in value and time.tzinfo else None


def uid(value):
    """A Swiss company UID as orbit writes it, CHE-123.456.789, however it was written: CHE123456789, che-123.456.789,
    CHE-123.456.789 MWST. Text that isn't one is returned as it was."""
    digits = re.sub(r"\D", "", value)
    return f"CHE-{digits[:3]}.{digits[3:6]}.{digits[6:]}" if value.strip().upper().startswith("CHE") else value


def clean(type_name, name, value):
    """A value a caller gives for a field, checked and normalized as orbit stores it: text trimmed, addresses and
    domains lowercased, choices in their spelling, times with their offset. None for an empty value. Links must
    already be wikilinks. Raises SchemaError, saying what's wrong."""
    field = TYPES[type_name].field(name)
    if field is None:
        allowed = ", ".join(f.name for f in TYPES[type_name].fields if not f.managed)
        raise SchemaError(f"{type_name} has no field {name!r}; its fields are {allowed}")
    if field.many:
        items = value if isinstance(value, list) else [value]
        cleaned = [_clean_one(field, item) for item in items]
        return list(dict.fromkeys(c for c in cleaned if c is not None)) or None
    if isinstance(value, list):
        raise SchemaError(f"{name} takes a single value, not a list")
    return _clean_one(field, value)


def _clean_one(field, value):
    if field.kind == "bool":
        if not isinstance(value, bool):
            raise SchemaError(f"{field.name} takes true or false")
        return value
    if value is None:
        return None
    if not isinstance(value, str):
        raise SchemaError(f"{field.name} takes text, not {type(value).__name__}")
    value = re.sub(r"\s+", " ", value).strip()
    if not value:
        return None
    if field.kind == "email":
        value = names.address(value) or names.email(value)  # as an email's header writes it, too
    elif field.kind == "domain":
        value = names.normalize_domain(value)
    elif field.kind == "sha256":
        value = value.lower()
    elif field.kind == "uid":
        value = uid(value)
    elif field.kind == "choice":
        value = next((c for c in field.choices if c.lower() == value.lower()), value)
    elif field.kind == "datetime" and (time := _datetime(value)):
        value = time.isoformat(timespec="seconds")
    elif field.kind == "datetime" and "T" in value and not _datetime(value):
        raise SchemaError(f"{field.name}: {value!r} needs its UTC offset, e.g. 2026-10-14T09:32:00+02:00")
    if message := _invalid(field, value):
        raise SchemaError(f"{field.name}: {message}")
    return value
