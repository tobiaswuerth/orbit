"""The write tools. Each names its source; refuses, with an error that says what to do instead, what would break the
vault's rules; changes nothing when called again with the same arguments, where it can; and returns the ids and
absolute paths of the notes it created or changed."""

from . import console, edits, evidence, ids, names, reads, resolve, schema
from .edits import Changes
from .entries import CONFIDENCE, Change, Observation
from .errors import OrbitError
from .schema import INTERACTION, ORGANIZATION, PERSON, TASK, TOPIC
from .sections import text_lines

RELATIONS = {
    PERSON: ("org", "reports_to", "assistant_of", "colleague_of", "introduced_by"),
    ORGANIZATION: ("parent",),
    INTERACTION: ("from", "to", "cc", "participants", "mentioned", "orgs", "topics"),
    TASK: ("related",),
    TOPIC: ("orgs", "people"),
}
CONTACTED = ("from", "to", "cc", "participants")  # the people an interaction counts as contact with; not `mentioned`
OPEN_TASKS = 50  # of those whom an interaction is with, the most log_interaction lists; it counts the rest
MANAGED = {
    "last_contact": "log_interaction sets it",
    "distinct_from": "answered reviews set it",
    "merged_from": "merges set it",
    "documents": "use link_document",
    "me": "only Me.md has it",
    "replies_to": "log_interaction sets it from in_reply_to and references",
}


def _result(entity_or_change, changes, **extra):
    return {k: entity_or_change[k] for k in ("id", "name", "path")} | extra | {"changed": list(changes)}


def _fields(crm, type_name, fields):
    """Fields a caller gives, checked and cleaned: links resolved to the notes they name, which must exist."""
    if not isinstance(fields, dict):
        raise OrbitError('fields: an object of field values, e.g. {"name": "Hans Müller", "emails": ["…"]}')
    spec, cleaned = schema.TYPES[type_name], {}
    for name, value in fields.items():
        field = spec.field(name)
        if field and field.managed:
            raise OrbitError(f"{name}: orbit sets it itself" + (f"; {MANAGED[name]}" if name in MANAGED else ""))
        if field and field.kind == "link" and value not in (None, "", []):
            if not field.many and not isinstance(value, str):
                raise OrbitError(f"{name} takes a single value, not a list")
            links = crm.links(value, field.to, role=name)
            value = links if field.many else links[0]
        if (value := schema.clean(type_name, name, value)) is not None:
            cleaned[name] = value
    return cleaned


def _date(value, role):
    text = str(value or "")[:10]
    if not schema.is_date(text):
        raise OrbitError(f"{role}: {value!r} is not a date (YYYY-MM-DD) or time")
    return text


# People, organizations and topics


def upsert_person(crm, match, fields, source, resolution_reason=None, provisional=False, distinct_from=None):
    return _upsert(crm, PERSON, match, fields, source, resolution_reason, provisional, distinct_from)


def upsert_organization(crm, match, fields, source, resolution_reason=None, distinct_from=None):
    return _upsert(crm, ORGANIZATION, match, fields, source, resolution_reason, distinct_from=distinct_from)


def upsert_topic(crm, match, fields, source, resolution_reason=None, distinct_from=None):
    return _upsert(crm, TOPIC, match, fields, source, resolution_reason, distinct_from=distinct_from)


# The score from which a new note is too like one there to be created: a person of the same full name, an organization
# whose name starts with, or is the initials of, another's, a topic sharing most of its words with another
ALIKE = {PERSON: 0.85, ORGANIZATION: 0.75, TOPIC: 0.7}


def _upsert(crm, type_name, match, fields, source, reason, provisional=False, distinct_from=None):
    if provisional and edits.listed(distinct_from):
        raise OrbitError(
            "provisional says it may be one of them, distinct_from that it is not: give one. Unsure: provisional, "
            "then propose_review; sure it is someone else: distinct_from"
        )
    link, date = crm.source(source)
    cleaned = _fields(crm, type_name, fields)
    new = isinstance(match, str) and match.strip().lower() == "new"
    existing = _retried(crm, type_name, cleaned, link, reason) if new else crm.find(match, (type_name,), role="match")
    distinct = [crm.find(ref, (type_name,), role="distinct_from") for ref in edits.listed(distinct_from)]
    extra = {}
    if type_name == PERSON:
        _check_emails(crm, cleaned.get("emails", []), existing)
        if org := _org_by_address(crm, cleaned, existing):
            cleaned["org"] = extra["org_from_domain"] = org.link
    if type_name == ORGANIZATION:
        _check_organization(crm, cleaned, existing)
    changes = Changes()
    if existing is None:
        if not provisional:
            _refuse_alike(crm, type_name, cleaned, distinct)
        note = new_entity(crm, type_name, cleaned, link, date, reason, provisional)
        edits.add_items(note, "distinct_from", [e.link for e in distinct])
        created = changes.add(crm.save(note, created=True))
        _reciprocate(crm, note, cleaned.get("colleague_of", []), changes)
        for other in distinct:
            changes.extend(_distinct(crm, other, note))
        return _result(created, changes, created=True, **extra)
    note = crm.load(existing.path)
    filled, added, conflicts = [], {}, []
    for name, value in cleaned.items():
        if schema.TYPES[type_name].field(name).many:
            if items := edits.add_items(note, name, value):
                added[name] = items
        elif note.fields.get(name) in (None, ""):
            edits.set_value(note, name, value, link, date)
            filled.append(name)
        elif not edits.same(note.fields[name], value):
            conflicts.append({"field": name, "stored": note.fields[name], "given": value})
    changes.add(crm.save(note))
    _reciprocate(crm, note, added.get("colleague_of", []), changes)
    extra |= {"hint": "set_fields changes a stored value"} if conflicts else {}
    entity = {"id": existing.id, "name": existing.name, "path": str(crm.vault.path(existing.path))}
    return _result(entity, changes, created=False, filled=filled, added=added, conflicts=conflicts, **extra)


def _org_by_address(crm, cleaned, existing):
    """The organization a person without one works at by the addresses given: see resolve.organization_of. None if an
    org is given or set, and for the owner, whose school or employer is theirs to say."""
    if cleaned.get("org") or (existing and (existing.fields.get("me") or existing.fields.get("org"))):
        return None
    return next(filter(None, (resolve.organization_of(crm, e) for e in cleaned.get("emails", []))), None)


def _refuse_alike(crm, type_name, cleaned, distinct):
    """Refuse a new note that is like one already there, as resolve_entity scores them, unless the caller says it is
    another (`distinct`). orbit takes calls one at a time, so of two callers that create one note at once, the second
    sees the first's."""
    if not cleaned.get("name"):
        return  # new_entity says what is missing
    domains = cleaned.get("domains", [])
    found = resolve.resolve(
        crm, type_name, [cleaned["name"], *cleaned.get("aliases", [])], cleaned.get("emails", []),
        domain=domains[0] if domains else None, org=schema.link_target(cleaned.get("org") or "") or None, limit=10,
    )  # fmt: skip
    told = {entity.id for entity in distinct}
    alike = [c for c in found["candidates"] if c["score"] >= ALIKE[type_name] and c["id"] not in told]
    if alike:
        listed = "; ".join(f"[[{c['name']}]] ({c['id']}, {c['score']}: {', '.join(c['reasons'][:2])})" for c in alike)
        unsure = "; if unsure, with provisional: true, then propose_review" if type_name == PERSON else ""
        raise OrbitError(
            f"name: {console.an(type_name)} alike is there already: {listed}. If it is one of them, call again with "
            f"its id as match; if not, with distinct_from: [its id], which is recorded on both{unsure}"
        )


def _distinct(crm, entity, note):
    """Record on a note that a new one is another, though alike; the changes."""
    other = crm.load(entity.path)
    edits.add_items(other, "distinct_from", [schema.link(note.name)])
    return [change for change in [crm.save(other)] if change]


def _retried(crm, type_name, cleaned, link, reason):
    """The note an earlier call with the same arguments created, when a "new" is repeated, say after a timeout: one
    of the type with the same name, created for the same reason from the same source. A topic named like an existing
    one is that one, since topics have no other identity. Otherwise None."""
    if type_name == TOPIC and cleaned.get("name"):
        paths = crm.index.lookup([("title", names.fold(cleaned["name"]))])
        return next((e for e in map(crm.entity, paths) if e.type == TOPIC), None)
    if not (isinstance(reason, str) and reason.strip() and cleaned.get("name")):
        return None
    rows = crm.index.db.execute(
        """SELECT c.path FROM changes c JOIN notes n ON n.path = c.path
           WHERE c.field = 'created' AND c.new = ? AND c.source = ? AND n.type = ?""",
        (" ".join(reason.split()), link, type_name),
    )
    named = (crm.entity(path) for (path,) in rows.fetchall())
    return next((e for e in named if names.fold(str(e.fields.get("name", ""))) == names.fold(cleaned["name"])), None)


def new_entity(crm, type_name, cleaned, link, date, reason, provisional):
    if not cleaned.get("name"):
        raise OrbitError(f'fields: a new {type_name} needs a "name"')
    if type_name != TOPIC and not (isinstance(reason, str) and reason.strip()):
        raise OrbitError(
            f"resolution_reason: say why this is a new {type_name}, e.g. "
            '"no candidate matched hans.mueller@acme-ag.example", or "provisional, possibly [[Hans Müller]]"'
        )
    fields = dict(cleaned)
    if type_name == PERSON:
        fields["review_status"] = "needs_review" if provisional else "confirmed"
    if type_name == TOPIC:
        fields.setdefault("status", "active")
    distinguisher = schema.link_target(fields.get("org")) if type_name == PERSON else None
    distinguisher = distinguisher or fields.get("location")
    history = (
        [Change(date, "created", None, " ".join(reason.split()), link).line()] if reason and reason.strip() else []
    )
    sections = [("Notes", [])] + ([("History", history)] if history else [])
    spec = schema.TYPES[type_name]
    note = crm.new(type_name, spec.folder, fields["name"], fields, sections, distinguisher)
    if note.name != fields["name"]:
        edits.add_items(note, "aliases", [fields["name"]])  # links by the plain name find it in Obsidian
    return note


def _check_emails(crm, emails, existing):
    for address in emails:
        if names.is_role_address(address, crm.vault.config.role_addresses):
            raise OrbitError(f"emails: {address} is a role address, which belongs to no person; leave it out")
        holder = crm.index.holder("email", address)
        if holder and (existing is None or holder != existing.path):
            other = crm.entity(holder)
            raise OrbitError(
                f"emails: {address} belongs to {other.link} ({other.id}). If this is the same person, call "
                f'upsert_person with match "{other.id}"; if not, leave the address out.'
            )


def _check_organization(crm, cleaned, existing):
    free = crm.vault.config.free_mail_domains
    pairs = [("domain", d) for d in cleaned.get("domains", [])]
    pairs += [("uid", cleaned["uid_che"])] if cleaned.get("uid_che") else []
    for kind, value in pairs:
        if kind == "domain" and value in free:
            raise OrbitError(f"domains: {value} is a free-mail domain, which says nothing about an organization")
        for path in crm.index.lookup([(kind, value)]):
            other = crm.entity(path)
            if other.type == ORGANIZATION and (existing is None or path != existing.path):
                raise OrbitError(
                    f"{'domains' if kind == 'domain' else 'uid_che'}: {value} belongs to {other.link} ({other.id}). "
                    f'If this is the same organization, call upsert_organization with match "{other.id}"; if not, '
                    "leave it out."
                )


def _moved(note, old, new):
    """A person's org changed: the old one joins former_orgs, and the new one leaves it. An old org that a hand edit
    made a list joins it item by item."""
    olds = [o for o in edits.listed(old) if isinstance(o, str) and o]
    former = [
        o
        for o in edits.listed(note.fields.get("former_orgs"))
        if not edits.same(o, new) and not any(edits.same(o, x) for x in olds)
    ]
    former += [o for o in olds if not edits.same(o, new)]
    if former:
        note.fields["former_orgs"] = former
    else:
        note.fields.pop("former_orgs", None)


def _reciprocate(crm, note, colleagues, changes):
    """Colleagues are colleagues both ways: add the person to each colleague's colleague_of."""
    for colleague in colleagues:
        other = crm.load(crm.find(colleague).path)
        edits.add_items(other, "colleague_of", [schema.link(note.name)])
        changes.add(crm.save(other))


# Links and documents


def link_entities(crm, entity, relation=None, to=None, source=None, links=None):
    """Link a note to another through one of its relation fields (`relation`, `to`), or to several at once (`links`,
    each {"relation": …, "to": …}), every one of them checked before any is written."""
    if (relation is None and to is None) == (links is None):
        raise OrbitError('give relation and to, or links: [{"relation": "to", "to": "Hans Müller"}, …]')
    single = links is None
    a = crm.find(entity, role="entity")
    targets = [(name, _target(crm, a, name, b)) for name, b in ([(relation, to)] if single else map(_pair, links))]
    link, date = crm.source(source)
    changes, linked = Changes(), []
    for name, b in targets:
        linked.append({"relation": name, "to": b.link, "linked": _link(crm, a, name, b, link, date, changes)})
    return {"entity": a.link} | (linked[0] if single else {"links": linked}) | {"changed": list(changes)}


def _pair(item):
    if not (isinstance(item, dict) and isinstance(item.get("relation"), str) and "to" in item):
        raise OrbitError('links: each a {"relation": …, "to": …}, e.g. {"relation": "to", "to": "Hans Müller"}')
    return item["relation"], item["to"]


def _target(crm, a, relation, to):
    """The note `to` names, checked as a link from `a` through `relation`."""
    if relation not in RELATIONS.get(a.type, ()):
        allowed, kind = ", ".join(RELATIONS.get(a.type, ())) or "none", console.an(a.type or "note of no type")
        raise OrbitError(f"relation: the relations of {a.link}, {kind}, are {allowed}")
    b = crm.find(to, schema.TYPES[a.type].field(relation).to or None, role="to", relation=relation)
    if a.path == b.path:
        raise OrbitError("to: a note can't be linked to itself")
    return b


def _link(crm, a, relation, b, link, date, changes):
    """Link `a` to `b` through `relation`, and what follows from it. Whether the link is new."""
    note, field = crm.load(a.path), schema.TYPES[a.type].field(relation)
    if field.many:
        added = edits.add_items(note, relation, [b.link])
    else:
        old, corrects = note.fields.get(relation), _set_by(note, relation, link)
        added = [b.link] if edits.set_value(note, relation, b.link, link, date) else []
        if added and a.type == PERSON and relation == "org":
            _moved(note, None if corrects else old, b.link)
    changes.add(crm.save(note))
    if added and relation == "colleague_of":
        _reciprocate(crm, note, [b.link], changes)
    if added and a.type == INTERACTION and relation in CONTACTED:
        _contacted(crm, note, [b.link], changes)
    return bool(added)


def _document(title, reference):
    """A document as notes record it: a Markdown link, the reference in <> if it has spaces or brackets."""
    title = _title(title or "")
    reference = str(reference or "").strip()
    if not title or not reference:
        raise OrbitError("document and title: a URL, file path or document id, and what the document is called")
    if any(c in reference for c in " ()<>"):
        if "<" in reference or ">" in reference:
            raise OrbitError("document: a reference can't contain < or >")
        reference = f"<{reference}>"
    return f"[{title}]({reference})"


def _document_line(item):
    """A document as the body lists it: a local file as a file:// link, which Obsidian opens, else as recorded."""
    match = schema.DOCUMENT.fullmatch(item)
    link = names.file_link(match[2].removeprefix("<").removesuffix(">"))
    return f"[{match[1]}]({link})" if link else item


def link_document(crm, entity, document, title, source):
    found = crm.find(entity, (PERSON, ORGANIZATION, INTERACTION, TOPIC), role="entity")
    item = _document(title, document)
    link, _ = crm.source(source)
    note = crm.load(found.path)
    reference = schema.DOCUMENT.fullmatch(item)[2]
    documents = [d for d in edits.listed(note.fields.get("documents")) if isinstance(d, str)]
    if any((m := schema.DOCUMENT.fullmatch(d)) and m[2] == reference for d in documents):
        return _result(_entity(crm, found), [], existing=True)
    edits.add_items(note, "documents", [item])
    line = f"- {_document_line(item)}" + ("" if found.type == INTERACTION else f" · {link}")
    note.body.append("Documents", [line], schema.TYPES[found.type].sections)
    return _result(_entity(crm, found), [crm.save(note)], existing=False)


def _entity(crm, entity):
    return {"id": entity.id, "name": entity.name, "path": str(crm.vault.path(entity.path))}


# Facts


def add_observation(crm, entity, statement, evidence, confidence, source, observed_at=None):
    found = crm.find(entity, schema.ENTITY, role="entity")
    if confidence not in CONFIDENCE:
        raise OrbitError(f"confidence: {' or '.join(CONFIDENCE)}")
    if not (isinstance(statement, str) and statement.strip() and isinstance(evidence, str) and evidence.strip()):
        raise OrbitError("statement and evidence: the fact, and the words of the source that state it")
    link, date = crm.source(source)
    _check_quote(crm, link, evidence)
    date = _date(observed_at, "observed_at") if observed_at else date
    observation = Observation.parse(Observation(date, statement, evidence, link, confidence).line())
    note = crm.load(found.path)
    known = [o for o in map(Observation.parse, note.body.lines("Observations") or []) if o]
    if any(_same_fact(o, observation) for o in known):
        return _result(_entity(crm, found), [], existing=True)
    note.body.append("Observations", [observation.line()], schema.TYPES[found.type].sections)
    return _result(_entity(crm, found), [crm.save(note)], existing=False)


def _check_quote(crm, link, quote):
    if (part := evidence.unquoted(crm, link, quote)) is not None:
        raise OrbitError(
            f"evidence: from «{part}» on, it isn't in {link} as written: quote its words exactly, and join parts that "
            "aren't together with …"
        )


def _same_fact(known, new):
    """Whether an observation a note holds is the new one again: the same statement from the same source (whose
    words may state several facts), or the same evidence from another, as an email sent twice or a fact repeated in
    a reply's quoted history give."""
    if known.source == new.source:
        return known.statement == new.statement
    return known.evidence.casefold() == new.evidence.casefold()


def set_fields(crm, entity, changes, source, observed_at, evidence=None, remove=None):
    found = crm.find(entity, schema.ENTITY, role="entity")
    observed = _date(observed_at, "observed_at")
    if not isinstance(changes, dict) or not (changes or remove):
        raise OrbitError('changes: an object of fields and their new values, e.g. {"job_title": "Head of Procurement"}')
    spec, link = schema.TYPES[found.type], crm.source(source)[0]
    taken = _removals(found, spec, remove or {})
    if isinstance(evidence, str) and evidence.strip():
        _check_quote(crm, link, evidence)
    for name in changes:
        field = spec.field(name)
        if field and field.many:
            raise OrbitError(f"{name} is a list: add to it with upsert_{found.type}, or link with link_entities")
    cleared = [k for k, v in changes.items() if v in (None, "")]
    cleaned = _fields(crm, found.type, changes)  # every field is checked, those to clear too
    if required := [k for k in cleared if k in spec.required]:
        raise OrbitError(f"{required[0]}: {console.an(found.type)} needs one; give the new one instead")
    note, applied, refused = crm.load(found.path), [], []
    history = [c for c in map(Change.parse, note.body.lines("History") or []) if c]
    created = next((c.date for c in history if c.field == "created"), note.fields.get("created", ""))
    for name in [*cleaned, *cleared]:
        value, stored = cleaned.get(name), note.fields.get(name)
        if edits.same(stored, value) or (stored in (None, "") and value is None):
            continue
        since = max([c.date for c in history if c.field == name] or [created if stored not in (None, "") else ""])
        if since > observed:
            refused.append({"field": name, "value": value, "stored": stored, "stored_since": since})
            if value is None:  # that a source names no value is no fact about the note
                continue
            statement = f"{name}: {value}; not applied, the stored value is from {since}"
            words = evidence if isinstance(evidence, str) and evidence.strip() else f"{name}: {value}"
            line = Observation(observed, statement, words, link, "medium").line()
            note.body.append("Observations", [line], spec.sections)
            continue
        corrects = _set_by(note, name, link)
        edits.set_value(note, name, value, link, observed)
        if found.type == PERSON and name == "org":
            _moved(note, None if corrects else stored, value)
        applied.append(name)
    removed = [
        {"field": n, "item": i}
        for n, items in taken.items()
        for i in edits.remove_items(note, n, items, link, observed)
    ]
    saved = Changes([c for c in [crm.save(note)] if c])
    for colleague in [r["item"] for r in removed if r["field"] == "colleague_of"]:  # colleagues both ways
        other = crm.load(crm.find(colleague).path)
        if edits.remove_items(other, "colleague_of", [schema.link(note.name)], link, observed):
            saved.add(crm.save(other))
    extra = {"removed": removed} if remove else {}
    return _result(_entity(crm, found), saved, applied=applied, not_applied=refused, **extra)


def _removals(found, spec, remove):
    """The items to take out of each list field, checked: {field: [item, …]}."""
    if not isinstance(remove, dict):
        raise OrbitError('remove: an object of list fields and the items to take out, e.g. {"emails": ["old@x.ch"]}')
    for name, items in remove.items():
        field = spec.field(name)
        if field is None:
            raise OrbitError(f"remove: {name} isn't a field of {console.an(found.type)}")
        if not field.many:
            raise OrbitError(f'remove: {name} isn\'t a list; clear it with changes: {{"{name}": null}}')
        if field.managed:
            raise OrbitError(f"remove: {name} is orbit's to keep")
        if not isinstance(items, list) or not all(isinstance(i, str) and i.strip() for i in items):
            raise OrbitError(f'remove: {name} takes a list of items, e.g. {{"{name}": ["…"]}}')
    return remove


def _set_by(note, field, link):
    """Whether this source gave the field its value, since or when the note was created: setting it again is a
    correction of its own, not news of a change."""
    history = [c for c in map(Change.parse, note.body.lines("History") or []) if c and c.field in (field, "created")]
    return bool(history) and history[-1].source == link


# Interactions


def log_interaction(
    crm,
    kind,
    date,
    subject=None,
    direction=None,
    sender=None,
    to=None,
    cc=None,
    participants=None,
    mentioned=None,
    orgs=None,
    topics=None,
    language=None,
    summary=None,
    decisions=None,
    key_quote=None,
    documents=None,
    message_id=None,
    in_reply_to=None,
    references=None,
    source_file=None,
    sha256=None,
):
    if message_id and (path := crm.index.holder("message_id", message_id.strip())):
        return _logged_already(crm, crm.entity(path))
    unknown = {"addresses": [], "people": [], "orgs": [], "topics": []}
    roles = []
    given_people = {"from": sender, "to": to, "cc": cc, "participants": participants, "mentioned": mentioned}
    people = {key: _addressed(crm, value, unknown, roles) for key, value in given_people.items()}
    given = {
        "kind": kind,
        "date": date,
        "direction": direction,
        "subject": subject,
        **people,
        "orgs": _known(crm, orgs, unknown["orgs"]),
        "topics": _known(crm, topics, unknown["topics"]),
        "language": language,
        "message_id": message_id,
        "in_reply_to": in_reply_to,
        "thread": _thread(crm, in_reply_to, references),
        "source_file": source_file,
        "sha256": sha256,
    }
    fields = _fields(crm, INTERACTION, given)
    for required in ("kind", "date"):
        if required not in fields:
            raise OrbitError(f"{required}: required")
    if answered := _answered(crm, in_reply_to, references):
        fields["replies_to"] = answered.link
    items = [_document(d.get("title"), d.get("document")) for d in documents or []] if documents else []
    if items:
        fields["documents"] = items
    day = fields["date"][:10]
    who = [schema.link_target(fields[k] if k == "from" else fields[k][0]) for k in CONTACTED if fields.get(k)]
    title = f"{day} {fields['kind'].capitalize()}" + (f" – {fields['subject']}" if fields.get("subject") else "")
    title += f" – {who[0]}" if not fields.get("subject") and who else ""
    if not message_id and (logged := _logged(crm, title, fields)):
        return _logged_already(crm, logged)
    sections = [
        ("Summary", text_lines(str(summary or "").strip())),
        ("Decisions", [f"- {' '.join(d.split())}" for d in decisions or [] if d.strip()]),
        ("Key quote", [f"> {line}" for line in str(key_quote or "").strip().splitlines()]),
        ("Documents", [f"- {_document_line(item)}" for item in items]),
        ("Original", _original(fields.get("source_file"))),
    ]
    folder = f"{schema.TYPES[INTERACTION].folder}/{day[:4]}/{day[:7]}"
    note = crm.new(INTERACTION, folder, title, fields, [(h, lines) for h, lines in sections if lines])
    changes = Changes()
    created = changes.add(crm.save(note, created=True))
    if fields.get("message_id"):
        _answer_replies(crm, note, fields["message_id"], changes)
    contacts = [fields["from"]] if fields.get("from") else []
    _contacted(crm, note, contacts + [p for k in ("to", "cc", "participants") for p in fields.get(k, [])], changes)
    extra = {f"unknown_{kind}": list(dict.fromkeys(found)) for kind, found in unknown.items() if found}
    extra |= {"role_addresses": list(dict.fromkeys(roles))} if roles else {}
    if any(unknown.values()):
        extra["hint"] = (
            "resolve each with resolve_entity (a name may be an alias); create those that are new with upsert_person, "
            "upsert_organization or upsert_topic, this interaction as source; then add them all with one "
            "link_entities call and `links`"
        )
    threaded = _thread_of(crm, note.path)
    in_thread = {t["name"] for t in threaded.get("thread", {}).get("open_tasks", [])}
    if tasks := [t for t in _open_tasks(crm, fields) if t["name"] not in in_thread]:
        extra["open_tasks"] = tasks[:OPEN_TASKS]
        extra |= {"open_tasks_more": len(tasks) - OPEN_TASKS} if len(tasks) > OPEN_TASKS else {}
    return _result(created, changes, existing=False, **extra, **threaded)


def _open_tasks(crm, fields):
    """The open tasks of the people and organizations an interaction is with, but the owner's own: those it may
    settle."""
    linked = [fields.get(k) for k in (*CONTACTED, "orgs")]
    involved = [crm.find(link) for link in dict.fromkeys(item for value in linked for item in edits.listed(value))]
    return reads.open_tasks(crm, [e for e in involved if not e.fields.get("me")])


def _logged_already(crm, entity):
    """The answer to logging an interaction again: the note, what it holds already (`recorded`), so that a retry after
    a failed run sees what is missing without reading it all, and its thread."""
    note = crm.load(entity.path)
    people = ("from", "to", "cc", "participants", "mentioned", "orgs", "topics")
    recorded = {k: note.fields[k] for k in people if note.fields.get(k) not in (None, "", [])}
    recorded |= {
        "summary": bool(note.body.lines("Summary")),
        "decisions": len(note.body.lines("Decisions") or []),
        "key_quote": bool(note.body.lines("Key quote")),
        "tasks": [line.removeprefix("- ") for line in note.body.lines("Action items") or [] if line.startswith("- ")],
        "documents": len(edits.listed(note.fields.get("documents"))),
    }
    return _result(_entity(crm, entity), [], existing=True, recorded=recorded, **_thread_of(crm, entity.path))


def _addressed(crm, value, unknown, roles):
    """The people a field of an interaction names, leaving out the email addresses of no one yet and the names of no
    note yet, which go to `unknown`, and role addresses, which go to `roles`."""
    if value is None or not isinstance(value, str | list):
        return value
    kept = []
    for ref in [value] if isinstance(value, str) else value:
        address = names.address(ref)
        if address and names.is_role_address(address, crm.vault.config.role_addresses):
            roles.append(address)
        elif address and not crm.index.holder("email", address):
            unknown["addresses"].append(address)
        elif not address and (name := _unknown_name(crm, ref)):
            unknown["people"].append(name)
        else:
            kept.append(ref)
    return kept if isinstance(value, list) else (kept[0] if kept else None)


def _known(crm, value, unknown):
    """The organizations or topics an interaction names, leaving out the names of no note yet, which go to
    `unknown`."""
    if not isinstance(value, list):
        return value
    kept = []
    for ref in value:
        if name := _unknown_name(crm, ref):
            unknown.append(name)
        else:
            kept.append(ref)
    return kept


def _unknown_name(crm, ref):
    """The name a reference gives, if it is a name and no note has it yet; else None, also for an id or address,
    which the checks of the fields then report."""
    if not isinstance(ref, str) or not ref.strip() or ids.is_valid(ref.strip()) or names.address(ref):
        return None
    try:
        crm.find(ref)
    except OrbitError:
        return schema.link_target(ref.strip()) or ref.strip()
    return None


def _original(source_file):
    """The lines of an interaction's Original section: a link to the file it was logged from, if that is a local
    document."""
    link = names.file_link(source_file)
    return [f"- [{_title(names.local_path(source_file).name)}]({link})"] if link else []


def _title(text):
    """Text as the title of a Markdown link: brackets as parentheses, on one line."""
    return " ".join(str(text).replace("[", "(").replace("]", ")").split())


def _answered(crm, in_reply_to, references):
    """The interaction an email answers: the one with its In-Reply-To's message id, or else the latest of its
    References that orbit knows."""
    for message_id in [in_reply_to, *reversed(references or [])]:
        if isinstance(message_id, str) and (path := crm.index.holder("message_id", message_id.strip())):
            return crm.entity(path)
    return None


def _answer_replies(crm, note, message_id, changes):
    """Replies logged before the email they answer now link it; one that can't be read any more is passed over, as
    the email is logged already."""
    for path in crm.index.lookup([("in_reply_to", message_id)]):
        if path == note.path:  # an email that names itself as the one it answers answers nothing
            continue
        try:
            reply = crm.load(path)
        except OrbitError:
            continue
        reply.fields["replies_to"] = schema.link(note.name)
        changes.add(crm.save(reply))


def _thread_of(crm, path):
    """{"thread": its view} for an interaction in a thread with others, or nothing."""
    view = reads.thread(crm, crm.entity(path))
    return {"thread": view} if view else {}


def _logged(crm, title, fields):
    """The interaction an earlier call with the same arguments logged, when one without a message id is repeated: one
    under the same file name, or the same with a number, with the same kind, time, subject and sender. Otherwise
    None."""
    key = names.file_key(names.file_name(title))
    rows = crm.index.db.execute(
        "SELECT path FROM claims WHERE kind = 'name' AND (value = ? OR (value > ? AND value < ?))",
        (key, f"{key} (", f"{key} (￿"),
    )
    keys = ("kind", "date", "subject", "from")
    for (path,) in rows.fetchall():
        found = crm.entity(path)
        if found.type == INTERACTION and all(found.fields.get(k) == fields.get(k) for k in keys):
            return found
    return None


def _thread(crm, in_reply_to, references):
    """The thread an email belongs to: that of the interaction it replies to, or else the first of its references,
    or else the message it replies to."""
    if in_reply_to and (path := crm.index.holder("message_id", in_reply_to.strip())):
        thread = crm.entity(path).fields.get("thread")
        if thread:
            return thread
    refs = [r.strip() for r in references or [] if isinstance(r, str) and r.strip()]
    return refs[0] if refs else in_reply_to


def _contacted(crm, interaction, people, changes):
    """Set the last_contact of the people an interaction was with, if it is newer; never on Me.md. Nothing if the
    interaction's date isn't one, as a hand edit can leave it (lint_vault lists it)."""
    date = interaction.fields.get("date")
    day = date[:10] if isinstance(date, str) else ""
    if not schema.is_date(day):
        return
    for person in dict.fromkeys(people):
        found = crm.find(person, (PERSON,))
        if found.fields.get("me"):
            continue
        note = crm.load(found.path)
        if str(note.fields.get("last_contact") or "") < day:
            edits.set_value(note, "last_contact", day, None, day, history=False)
            changes.add(crm.save(note))


# Tasks


def create_task(
    crm, title, owner, origin, status="open", due=None, due_note=None, related=None, details=None, match=None
):
    """A new task; the same title from the same origin again is the task made then. An open task like it, in the
    same thread or for the same owner and matter, is refused unless `match` says "new", or names the task it is."""
    if not isinstance(title, str) or not title.strip():
        raise OrbitError(
            "title: what is to be done, as the task's name, e.g. Send revised offer for Wartungsvertrag 2027"
        )
    origin_link = crm.links(origin, role="origin")[0] if origin else None
    if origin_link is None:
        raise OrbitError("origin: the interaction the task comes from; log it with log_interaction first")
    stem = names.file_name(title)
    for task in crm.entities(TASK):
        same_name = task.name == stem or task.name.startswith(f"{stem} (")
        if same_name and edits.same(task.fields.get("origin"), origin_link):
            return _result(_entity(crm, task), [], existing=True)
    new = isinstance(match, str) and match.strip().lower() == "new"
    if match is not None and not new:
        return _result(_entity(crm, crm.find(match, (TASK,), role="match")), [], existing=True)
    fields = _fields(
        crm,
        TASK,
        {"status": status, "due": due, "due_note": due_note, "owner": owner, "related": related, "origin": origin_link},
    )
    if "owner" not in fields:
        raise OrbitError("owner: who is to do it, a person or an organization; Me for the owner")
    if not new and (similar := _similar_tasks(crm, title, fields)):
        raise OrbitError(
            f"similar open tasks: {', '.join(f'{t.link} ({t.id})' for t in similar)}. If this is one of them, call "
            "create_task with its id as match, or update_task it; if it is another task, call create_task again "
            'with match "new".'
        )
    quoted = [f"> {line}" for line in str(details or "").strip().splitlines()]
    note = crm.new(
        TASK, schema.TYPES[TASK].folder, " ".join(title.split()), fields, [("Details", quoted), ("Notes", [])]
    )
    changes = Changes()
    created = changes.add(crm.save(note, created=True))
    source = crm.find(origin_link)
    if source.type == INTERACTION:
        interaction = crm.load(source.path)
        item = f"- {schema.link(note.name)}"
        if item not in (interaction.body.lines("Action items") or []):
            interaction.body.append("Action items", [item], schema.TYPES[INTERACTION].sections)
            changes.add(crm.save(interaction))
    return _result(created, changes, existing=False)


def _similar_tasks(crm, title, fields):
    """Open tasks that may be the one a title describes: a title like it, and an origin in the same thread, or the
    same owner and a related note in common."""
    origin = crm.find(fields["origin"])
    thread = reads.thread_members(crm, origin) if origin.type == INTERACTION else [origin]
    related = edits.listed(fields.get("related"))
    words = _title_words(title)
    found = []
    for task in crm.entities(TASK):
        theirs = task.fields
        same_thread = any(edits.same(theirs.get("origin"), t.link) for t in thread)
        same_matter = edits.same(theirs.get("owner"), fields["owner"]) and any(
            edits.same(r, x) for r in related for x in edits.listed(theirs.get("related"))
        )
        theirs_words = _title_words(task.name)
        shared = words & theirs_words
        alike = len(shared) >= 2 and len(shared) >= 0.6 * min(len(words), len(theirs_words))
        if theirs.get("status") in reads.OPEN and (same_thread or same_matter) and alike:
            found.append(task)
    return found


def _title_words(title):
    """The words of a title that say what it is about: those of four letters or more."""
    return {w for w in names.words(title) if len(w) >= 4}


def update_task(crm, task, source, status=None, due=None, due_note=None, note=None):
    found = crm.find(task, (TASK,), role="task")
    if status is None and due is None and due_note is None and not (isinstance(note, str) and note.strip()):
        raise OrbitError("give what changed: status, due, due_note or a note")
    link, date = crm.source(source)
    cleaned = _fields(crm, TASK, {"status": status, "due": due, "due_note": due_note})
    page, said = crm.load(found.path), []
    for name, value in cleaned.items():
        if change := edits.set_value(page, name, value, link, date, history=False):
            said.append(f"{name}: {change.old or 'none'} → {value}")
    if isinstance(note, str) and note.strip():
        said.append(" ".join(note.split()))
    if not said:
        return _result(_entity(crm, found), [], updated=False)
    page.body.append("Details", [f"- {date} · {'; '.join(said)} · {link}"], schema.TYPES[TASK].sections)
    return _result(_entity(crm, found), [crm.save(page)], updated=True)
