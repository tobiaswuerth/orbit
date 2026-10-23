"""The read tools: a note in context, full-text and fuzzy search, and structured queries over front matter."""

import json
import re

from . import edits, names, schema
from .entries import Change, Observation
from .errors import OrbitError

RECENT = 10  # interactions in a note's context
OBSERVATIONS = 50
OPEN = ("open", "waiting")
COMPARISONS = ("<", "<=", ">", ">=")


ANSWERED = 10  # the latest answered reviews a note's context shows


def context(crm, ref, since=None):
    """A note's fields, recent observations, the last change of each field, its links in and out, recent
    interactions, open tasks, and reviews about it, pending and answered."""
    if since is not None and not schema.is_date(str(since)[:10]):
        raise OrbitError(f"since: {since!r} is not a date (YYYY-MM-DD)")
    since = since and str(since)[:10]
    entity = crm.find(ref, role="id_or_name")
    note = crm.load(entity.path)
    entity = crm.entity(entity.path)  # as the note is now, if it was edited since it was indexed
    found = {"id": entity.id, "type": entity.type, "name": entity.name, "path": str(crm.vault.path(entity.path))}
    found["fields"] = entity.fields
    observations = [o for o in map(Observation.parse, note.body.lines("Observations") or []) if o]
    observations = [o.__dict__ for o in observations if not since or o.date >= since]
    if observations:
        found["observations"] = sorted(observations, key=lambda o: o["date"], reverse=True)[:OBSERVATIONS]
    changes = [c for c in map(Change.parse, note.body.lines("History") or []) if c]
    if changes:
        found["last_changes"] = {c.field: _change(c) for c in sorted(changes, key=lambda c: c.date)}
    found["links_out"] = _links_out(crm, entity)
    incoming = _links_in(crm, entity)
    found["links_in"] = [i for i in incoming if i["type"] not in (schema.INTERACTION, schema.TASK, schema.REVIEW)]
    interactions = [
        i for i in incoming if i["type"] == schema.INTERACTION and str(i.get("date", ""))[:10] >= (since or "")
    ]
    found["interactions"] = sorted(interactions, key=lambda i: str(i.get("date", "")), reverse=True)[:RECENT]
    found["open_tasks"] = [i for i in incoming if i["type"] == schema.TASK and i.get("status") in OPEN]
    found["pending_reviews"] = [i for i in incoming if i["type"] == schema.REVIEW and i.get("decision") == "pending"]
    found["answered_reviews"] = [  # what the owner said, so that nobody asks again
        i for i in incoming if i["type"] == schema.REVIEW and i.get("decision") not in (None, "pending")
    ][-ANSWERED:]
    if entity.type == schema.INTERACTION and (view := thread(crm, entity)):
        found["thread"] = view
    managed = {"Observations", "History"}
    found["sections"] = {h: "\n".join(note.body.lines(h)) for h in note.body.headings() if h not in managed}
    return found


def thread(crm, interaction):
    """An interaction's thread, as orbit knows it from message ids: its interactions, oldest first; the topics they
    concern; and the open tasks they gave rise to. None if the interaction is alone in it."""
    members = thread_members(crm, interaction)
    if len(members) < 2:
        return None
    keys = ("date", "kind", "from", "subject")
    tasks = [t for m in members for t in _links_in(crm, m) if t["type"] == schema.TASK and "origin" in t["via"]]
    return {
        "interactions": [
            {"id": m.id, "name": m.name} | {k: m.fields[k] for k in keys if m.fields.get(k) not in (None, "")}
            for m in members
        ],
        "topics": list(
            dict.fromkeys(t for m in members for t in edits.listed(m.fields.get("topics")) if schema.link_target(t))
        ),
        "open_tasks": [t for t in tasks if t.get("status") in OPEN],
    }


def thread_members(crm, interaction):
    """The interactions in an interaction's thread, itself among them, oldest first."""
    keys = [k.strip() for k in (interaction.fields.get(f) for f in ("thread", "message_id")) if isinstance(k, str)]
    paths = {interaction.path, *crm.index.lookup([("thread", k) for k in keys if k])}
    members = [e for e in map(crm.entity, paths) if e.type == schema.INTERACTION]
    return sorted(members, key=lambda e: (str(e.fields.get("date", "")), e.path))


def _change(change):
    found = {"date": change.date, "source": change.source}
    return found | ({"reason": change.new} if change.field == "created" else {"old": change.old, "new": change.new})


def _links_out(crm, entity):
    rows = crm.index.db.execute(
        """SELECT l.field, l.target, n.id, n.type FROM links l LEFT JOIN claims c ON c.kind = 'name'
           AND c.value = l.target_key AND c.owner LEFT JOIN notes n ON n.path = c.path
           WHERE l.path = ? AND l.field IS NOT NULL ORDER BY l.rowid""",
        (entity.path,),
    )
    return [{"field": r["field"], "name": r["target"], "id": r["id"], "type": r["type"]} for r in rows]


def _links_in(crm, entity):
    """The notes whose front matter links to this one, each once, with the fields that do and what describes them."""
    rows = crm.index.db.execute(
        """SELECT n.path, n.id, n.type, n.name, n.fields, group_concat(DISTINCT l.field) AS via FROM links l
           JOIN notes n ON n.path = l.path WHERE l.target_key = ? AND l.field IS NOT NULL AND n.path != ?
           GROUP BY n.path ORDER BY n.path""",
        (names.file_key(entity.name), entity.path),
    )
    found = []
    for r in rows:
        fields = json.loads(r["fields"])
        item = {"id": r["id"], "type": r["type"], "name": r["name"], "via": sorted(r["via"].split(","))}
        keys = {
            schema.INTERACTION: ("date", "kind", "direction", "subject"),
            schema.TASK: ("status", "due", "owner"),
            schema.REVIEW: ("kind", "question", "decision"),
        }.get(r["type"], ())
        found.append(item | {k: fields[k] for k in keys if fields.get(k) not in (None, "")})
    return found


def search(crm, query, type=None, limit=10):
    """Notes matching words, best first: by full-text search over names, aliases, addresses, domains, roles and body
    text, with names also matched without umlauts and accents, and by the sound of a surname."""
    if type is not None and type not in schema.TYPES:
        raise OrbitError(f"type: one of {', '.join(schema.TYPES)}")
    limit = max(0, limit)
    words = re.findall(r"[^\W_]+", query or "")
    if not words:
        raise OrbitError("query: the words to look for, such as a name, an address or a job title")
    terms = [" OR ".join(f'"{w}"*' for w in dict.fromkeys([word, names.fold(word)])) for word in words]
    found, seen = [], set()
    for match in (" AND ".join(f"({t})" for t in terms), " OR ".join(f"({t})" for t in terms)):
        rows = crm.index.db.execute(
            f"""SELECT n.path, bm25(search, 10.0, 5.0, 2.0, 1.0) AS rank FROM search
                JOIN notes n ON n.num = search.rowid
                WHERE search MATCH ? {"AND n.type = ?" if type else ""} ORDER BY rank LIMIT ?""",
            (match, *([type] if type else []), limit),
        )
        for row in rows:
            seen.add(row["path"])
            found.append(_hit(crm, row["path"], round(-row["rank"], 3), "words"))
        if found:
            break
    if len(found) < limit and type in (None, schema.PERSON):
        sounds = [("sound", names.koelner(w)) for w in words if len(w) > 2]
        for path in crm.index.lookup(sounds):
            if path not in seen and len(found) < limit:
                seen.add(path)
                found.append(_hit(crm, path, 0.0, "sound"))
    return found


def _hit(crm, path, score, matched):
    entity = crm.entity(path)
    keys = {
        schema.PERSON: ("org", "job_title", "emails"),
        schema.ORGANIZATION: ("domains", "location"),
        schema.INTERACTION: ("date", "kind", "subject"),
        schema.TASK: ("status", "due", "owner"),
        schema.TOPIC: ("status",),
        schema.REVIEW: ("kind", "decision"),
    }.get(entity.type, ())
    found = {"id": entity.id, "type": entity.type, "name": entity.name, "path": str(crm.vault.path(path))}
    found |= {"score": score, "matched": matched}
    return found | {k: entity.fields[k] for k in keys if entity.fields.get(k) not in (None, "", [])}


def list_entities(crm, type, filters=None, sort=None, limit=50):
    """Notes of a type whose front matter meets every filter, sorted by a field."""
    if type not in schema.TYPES:
        raise OrbitError(f"type: one of {', '.join(schema.TYPES)}")
    filters = filters or {}
    if not isinstance(filters, dict):
        raise OrbitError('filters: an object of field conditions, e.g. {"status": "open"}')
    spec = schema.TYPES[type]
    asked = [*filters, *([sort.removeprefix("-")] if sort else [])]
    if unknown := [f for f in asked if not spec.field(f)]:  # a field added by hand is fine, if a note has it
        added = {k for e in crm.entities(type) for k in e.fields}
        if missing := [f for f in unknown if f not in added]:
            raise OrbitError(f"{type} has no field {missing[0]!r}; its fields are {', '.join(spec.names)}")
    paths = _linked(crm, spec, filters)
    found = (
        crm.index.rows(type) if paths is None else [r for r in map(crm.index.row, sorted(paths)) if r["type"] == type]
    )
    rows = [crm.entity_of(r) for r in found]
    kept = [e for e in rows if all(_meets(e.fields.get(f), c, f) for f, c in filters.items())]
    if sort:
        field = sort.removeprefix("-")
        present = sorted(
            (e for e in kept if e.fields.get(field) not in (None, "", [])),
            key=lambda e: str(e.fields[field]),
            reverse=sort.startswith("-"),
        )
        kept = present + [e for e in kept if e.fields.get(field) in (None, "", [])]
    results = [{"id": e.id, "name": e.name, "path": str(crm.vault.path(e.path)), "fields": e.fields} for e in kept]
    return {"total": len(kept), "results": results[: max(0, limit)]}


def _linked(crm, spec, filters):
    """The notes that conditions on link fields can hold for, from the index's links; None if there are no such
    conditions. A large vault then reads only the notes that link to the ones asked for."""
    paths = None
    for name, condition in filters.items():
        field, wanted = spec.field(name), condition if isinstance(condition, list) else [condition]
        if not (field and field.kind == "link" and wanted and all(isinstance(w, str) for w in wanted)):
            continue
        found = set()
        for value in wanted:
            key = names.file_key(schema.link_target(value) or value)
            rows = crm.index.db.execute("SELECT path FROM links WHERE field = ? AND target_key = ?", (name, key))
            found |= {r[0] for r in rows}
        paths = found if paths is None else paths & found
    return paths


def _meets(value, condition, field):
    """Whether a field's value meets a condition: a value (which a list field meets if it holds it), a list of values
    (any of them), {"not": value or list}, {"exists": true or false}, or comparisons such as {">=": "2026-01"}, which
    compare at the precision given."""
    if isinstance(condition, dict):
        unknown = set(condition) - {*COMPARISONS, "not", "exists"}
        if unknown:
            raise OrbitError(
                f"{field}: unknown condition {sorted(unknown)[0]!r}; use a value, a list, not, exists, <, <=, >, >="
            )
        ok = True
        if "exists" in condition:
            ok &= (value not in (None, "", [])) == bool(condition["exists"])
        if "not" in condition:
            ok &= not _meets(value, condition["not"], field)
        for op in COMPARISONS:
            if op in condition:
                if value in (None, "", []):
                    return False
                bound = str(condition[op])
                have = str(value)[: len(bound)]
                ok &= {"<": have < bound, "<=": have <= bound, ">": have > bound, ">=": have >= bound}[op]
        return ok
    wanted = condition if isinstance(condition, list) else [condition]
    return any(edits.same(v, w) for v in edits.listed(value) for w in wanted)
