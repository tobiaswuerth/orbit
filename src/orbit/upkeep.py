"""Upkeep: renaming a note, merging two notes about the same person, organization or topic, applying the decisions
set on reviews, and the links that follow them all. Links are rewritten wherever they are, as Obsidian rewrites them
when a note is renamed: in front matter and in every section of the body."""

import re
from pathlib import PurePosixPath

from . import console, edits, names, reads, resolve, reviews, schema, writes
from .edits import Changes
from .entries import Change
from .errors import OrbitError
from .schema import REVIEW, TASK

CANCEL_BOX = "the owner's Cancel box"  # the source of a task cancelled by its box

LINK = re.compile(r"\[\[([^\[\]|#^]+)((?:[#^|][^\[\]]*)?)\]\]")
PLURALS = reviews.PLURALS  # the types a duplicate review is about
KINDS = PLURALS  # the types merged: those a duplicate review is about
APPENDED = ("Observations", "Documents")  # sections whose lines a merge adds, each once
NOT_COPIED = {"type", "id", "name", "aliases", "me", "created", "updated", "merged_from", "review_status"}
# What a duplicate review's decision says: yes and no too, as owners answer "Is Hans the same person as ...?"
DUPLICATE_ANSWERS = {"same": "same", "yes": "same", "different": "different", "no": "different"}


def rewrite_links(text, old, new):
    """Text with every wikilink to the note named `old` naming `new` instead, however it is written: with a path,
    with .md, with a heading, block or display text, or as an embed."""
    key = names.file_key(old)

    def rewritten(match):
        name = match[1].strip().rsplit("/", 1)[-1].removesuffix(".md")
        return f"[[{new}{match[2]}]]" if names.file_key(name) == key else match[0]

    return LINK.sub(rewritten, text)


def relink(crm, old, new, changes):
    """Make every link to `old` in the vault link to `new`, so that links follow a note renamed or merged. The notes
    that couldn't be read, and so still link to `old`, each with the reason."""
    rows = crm.index.db.execute(
        "SELECT DISTINCT path FROM links WHERE target_key = ? ORDER BY path", (names.file_key(old),)
    )
    left = []
    for path in [r[0] for r in rows.fetchall()]:
        try:
            note = crm.load(path)
        except OrbitError as e:
            left.append(_left(crm, path, e))
            continue
        for field, value in list(note.fields.items()):
            if isinstance(value, str):
                note.fields[field] = rewrite_links(value, old, new)
            elif isinstance(value, list):
                note.fields[field] = [rewrite_links(v, old, new) if isinstance(v, str) else v for v in value]
        _unlink_self(note, [note.name])
        note.body.rewrite(lambda line: rewrite_links(line, old, new))
        changes.add(crm.save(note))
    return left


def _left(crm, path, error):
    return {"note": PurePosixPath(path).stem, "path": str(crm.vault.path(path)), "reason": str(error)}


def _unlink_self(note, selves):
    """Take links to these names out of a note's link fields, and repeats out of its lists: a note doesn't link to
    itself, nor twice to the same note in one field."""
    spec = schema.TYPES.get(note.type)
    for field in [f for f in spec.fields if f.kind == "link"] if spec else []:
        value = note.fields.get(field.name)
        if value is None:
            continue
        kept = []
        for item in edits.listed(value):
            if not any(edits.same(item, schema.link(s)) for s in selves) and not any(edits.same(item, k) for k in kept):
                kept.append(item)
        if kept:
            note.fields[field.name] = kept if field.many else kept[0]
        else:
            note.fields.pop(field.name)


def rename(crm, ref, new_name, source):
    found = crm.find(ref, role="id_or_name")
    if not isinstance(new_name, str) or not new_name.strip():
        raise OrbitError("new_name: the note's new name, as links will write it")
    if found.fields.get("me"):
        raise OrbitError("Me.md keeps its name: notes link to the owner as [[Me]]")
    link, date = crm.source(source)
    new_name = " ".join(new_name.split())
    stem = names.file_name(new_name)
    if stem == found.name:
        return _result(crm, found, found.path, [])
    holder = crm.index.holder("name", names.file_key(stem))
    if holder and holder != found.path:
        raise OrbitError(f"new_name: a note called {stem} exists already: {crm.entity(holder).link}")
    note, changes = crm.load(found.path), Changes()
    spec = schema.TYPES.get(note.type)
    if spec and spec.field("name") and note.fields.get("name") == found.name:
        edits.set_value(note, "name", new_name, link, date)
    if spec and spec.field("aliases") and names.file_key(stem) != names.file_key(found.name):
        edits.add_items(note, "aliases", [found.name])
    path = str(PurePosixPath(found.path).with_name(f"{stem}.md"))
    crm.vault.rename(found.path, path)
    crm.index.refresh([found.path, path])
    note.path = path
    changes.add(crm.save(note) or crm.describe(note, "renamed"))
    left = relink(crm, found.name, stem, changes)
    return _result(crm, found, path, changes) | {"links_left": left}


def merge(crm, keep, drop, source, overrule=False):
    """Merge `drop` into `keep`; see the merge_entities tool. `overrule`: the owner says the two are one, so what
    recorded them as different comes off both, with a history line."""
    k = crm.find(keep, schema.ENTITY, role="keep")
    d = crm.find(drop, (k.type,), role="drop")
    if k.path == d.path:
        raise OrbitError("keep and drop are the same note")
    if d.fields.get("me"):
        raise OrbitError("drop: Me.md can't be merged into another note; merge the other note into Me instead")
    for role, entity in (("keep", k), ("drop", d)):
        if not entity.id:
            raise OrbitError(f"{role}: {entity.link} has no id yet; lint_vault with fix gives it one")
    link, date = crm.source(source)
    note, other = crm.load(k.path), crm.load(d.path)
    if overrule:
        _undistinct(note, d, link, date)
        _undistinct(other, k, link, date)
    elif _distinct(note, d) or _distinct(other, k):
        raise OrbitError(
            f"{k.link} and {d.link} are recorded as different {KINDS[k.type]}; only the owner can say otherwise: "
            "propose_review a duplicate, which returns their answer if they gave one, and their yes merges the two"
        )
    conflicts = _merge_fields(note, other, k, d)
    taken = {c["field"] for c in conflicts}
    for heading in other.body.headings():
        lines = other.body.lines(heading)
        if heading in APPENDED:
            ours = note.body.lines(heading) or []
            note.body.append(heading, [x for x in lines if x not in ours], schema.TYPES[k.type].sections)
        elif heading == "History":
            ours = note.body.lines(heading) or []
            kept = [x for x in lines if x not in ours and getattr(Change.parse(x), "field", None) not in taken]
            note.body.append(heading, kept, schema.TYPES[k.type].sections)
        elif lines:
            note.body.append(heading, [f"From {d.name}, merged on {date}:", *lines], schema.TYPES[k.type].sections)
    writes.drop_retracted(note, schema.TYPES[k.type].sections)  # what either had taken back stays out
    merged = Change(date, "merged", None, f"{d.name} ({d.id})", link).line()
    note.body.append("History", [merged], schema.TYPES[k.type].sections)
    changes = Changes()
    changes.add(crm.save(note))
    crm.vault.trash(d.path)  # as Obsidian deletes a note: into .trash, from where it can be restored
    crm.index.refresh([d.path])
    left = _answer_reviews(crm, k, d, changes) + relink(crm, d.name, k.name, changes)
    result = {"id": note.fields["id"], "name": k.name, "path": str(crm.vault.path(k.path)), "conflicts": conflicts}
    result["links_left"] = list({n["path"]: n for n in left}.values())
    if conflicts:
        review = reviews.propose(
            crm,
            "other",
            f"{d.name} was merged into {k.name}, which kept its own values where the two differed. Are they right?",
            [k.link],
            [f"{c['field']}: kept {c['kept']}" for c in conflicts],
            [f"{c['field']}: {d.name} had {c['dropped']}" for c in conflicts],
            source,
        )
        result["review"] = {key: review[key] for key in ("id", "name", "path")}
        changes.extend(review.get("changed", []))
    return result | {"changed": list(changes)}


def _distinct(note, entity):
    """Whether a note records another as different."""
    return any(edits.same(x, entity.link) for x in edits.listed(note.fields.get("distinct_from")))


def _undistinct(note, entity, source, date):
    """Take another note off a note's distinct_from, with a history line that names it in text, which the links
    rewritten by a merge leave as it is."""
    if not _distinct(note, entity):
        return
    kept = [x for x in edits.listed(note.fields["distinct_from"]) if not edits.same(x, entity.link)]
    if kept:
        note.fields["distinct_from"] = kept
    else:
        del note.fields["distinct_from"]
    line = Change(date, "distinct_from", entity.name, None, source).line()
    note.body.append("History", [line], schema.TYPES[note.type].sections)


def _merge_fields(note, other, k, d):
    """Merge the other note's fields into the note: lists united, blank fields filled, the older id kept. The fields
    whose values differ, which keep the note's."""
    spec, fields, theirs = schema.TYPES[k.type], note.fields, other.fields
    conflicts = []
    for name, value in theirs.items():
        field, current = spec.field(name), fields.get(name)
        if name in NOT_COPIED or value in (None, "", []):
            continue
        if field and field.many:
            edits.add_items(note, name, edits.listed(value))
        elif name == "last_contact":
            fields[name] = max(str(current or ""), str(value))
        elif current in (None, "", []):
            fields[name] = value
        elif name == "context" and current != value:
            fields[name] = "both"
        elif not edits.same(current, value):
            conflicts.append({"field": name, "kept": current, "dropped": value})
    own = {names.file_key(n) for n in (k.name, str(fields.get("name", "")))}
    aliases = [theirs.get("name"), d.name, *edits.listed(theirs.get("aliases"))]
    edits.add_items(note, "aliases", [a for a in aliases if isinstance(a, str) and names.file_key(a) not in own])
    older, newer = sorted([fields["id"], theirs["id"]], key=lambda i: i.partition("_")[2])
    fields["id"] = older
    edits.add_items(note, "merged_from", [newer, *edits.listed(theirs.get("merged_from"))])
    if dates := [x for x in (fields.get("created"), theirs.get("created")) if isinstance(x, str) and x]:
        fields["created"] = min(dates)
    if k.type == schema.PERSON:
        fields["review_status"] = "confirmed"
    _unlink_self(note, [k.name, d.name])
    return conflicts


def _answer_reviews(crm, k, d, changes):
    """A merge answers the pending duplicate reviews that ask about the two: they are decided `same`. The reviews
    that couldn't be read, each with the reason."""
    left = []
    for review in crm.entities(REVIEW):
        candidates = {
            names.file_key(schema.link_target(c) or "") for c in edits.listed(review.fields.get("candidates"))
        }
        pending = review.fields.get("kind") == "duplicate" and review.fields.get("decision") == "pending"
        if pending and candidates == {names.file_key(k.name), names.file_key(d.name)}:
            try:
                note = crm.load(review.path)
            except OrbitError as e:
                left.append(_left(crm, review.path, e))
                continue
            note.fields["decision"] = "same"
            changes.add(crm.save(note))
    return left


def apply_task_boxes(crm, paths=None):
    """Keep the tasks' Cancel boxes, of every task or those at these paths: an open or waiting task has one, and
    ticked, it cancels the task, which says so and when; a closed task has none. The notes changed."""
    changes = Changes()
    for task in crm.entities(TASK):
        if paths is not None and task.path not in paths:
            continue
        try:
            if task.fields.get("cancel") is True and task.fields.get("status") in reads.OPEN:
                for change in writes.update_task(crm, task.id or task.name, CANCEL_BOX, status="cancelled")["changed"]:
                    changes.add(change)
            elif writes.boxed(task.fields) != task.fields:
                note = crm.load(task.path)
                note.fields = writes.boxed(note.fields)
                changes.add(crm.save(note))
        except OrbitError:  # a note broken since it was indexed: lint says so
            continue
    return changes


def apply_reviews(crm):
    """Apply the decisions set on reviews, or ticked in their boxes. A duplicate's `same` merges the newer note into
    the older one, even where an agent recorded them as different; `different` adds each note to the other's
    `distinct_from`, and confirms a provisional one. An address's `yes` adds it to the person's emails; a job change's
    `yes`, about a person and an organization, makes it their organization and the one before a former one; these are
    applied once, and marked `applied`, so that an edit made later stays. Applying a decision twice changes nothing.
    What couldn't be applied is kept for lint_vault, in `crm.review_problems`. The notes changed."""
    changes, crm.review_problems = Changes(), {}
    for review in crm.entities(REVIEW):
        review = _ticked(crm, review, changes)
        decision = review.fields.get("decision") if isinstance(review.fields.get("decision"), str) else None
        kind = review.fields.get("kind")
        if isinstance(kind, str) and kind in ACTS and decision in ("yes", "same") and not review.fields.get("applied"):
            _act(crm, review, changes)
        elif kind == "question" and decision == "pending":
            _answered(crm, review, changes)
        else:
            _decide_duplicate(crm, review, decision, changes)
    return changes


def _ticked(crm, review, changes):
    """A yes-or-no review the owner answered by ticking a box gets the decision it says; a pending one from before the
    boxes gets them. The review as it is now."""
    fields, kind = review.fields, review.fields.get("kind")
    if fields.get("decision") != "pending" or kind not in reviews.TICKED:
        return review
    yes, no = fields.get("answer_yes") is True, fields.get("answer_no") is True
    if yes and no:
        crm.review_problems[review.path] = "both Yes and No are ticked: untick the one that doesn't hold"
        return review
    if not (yes or no) and "answer_yes" in fields and "answer_no" in fields:
        return review
    try:
        note = crm.load(review.path)
    except OrbitError as e:
        crm.review_problems[review.path] = str(e)
        return review
    if yes or no:
        note.fields["decision"] = reviews.TICKED[kind][yes]
    else:
        note.fields |= {box: note.fields.get(box, False) for box in ("answer_yes", "answer_no")}
    changes.add(crm.save(note))
    return crm.entity(review.path)


def _answered(crm, review, changes):
    """An open question the owner wrote an answer to is answered: agents find it so."""
    note = crm.load(review.path)
    if reviews.answer(note):
        note.fields["decision"] = "answered"
        changes.add(crm.save(note))


def _act(crm, review, changes):
    """Apply an address review or a job change answered yes, once."""
    kind = review.fields["kind"]
    try:
        found = [crm.find(c) for c in edits.listed(review.fields.get("candidates"))]
        changed = ACTS[kind](crm, review, found)
    except OrbitError as e:
        crm.review_problems[review.path] = f"decided yes, but orbit couldn't {DONE[kind]}: {e}"
        return
    if changed is None:  # a question orbit has nothing to do for
        return
    note = crm.load(review.path)
    note.fields["applied"] = crm.today()
    changes.extend([*changed, crm.save(note)])


def _add_address(crm, review, found):
    address = review.fields.get("address")
    if len(found) != 1 or found[0].type != schema.PERSON or not isinstance(address, str):
        raise OrbitError("an address review names one person, and the address")
    address = names.email(address)
    if names.is_role_address(address, crm.vault.config.role_addresses):
        raise OrbitError(f"{address} is a role address, which belongs to no person")
    if (holder := crm.index.holder("email", address)) and holder != found[0].path:
        asked = _asked_whether_one(crm, review, address, found[0], holder)
        raise OrbitError(f"{address} belongs to {crm.entity(holder).link}{asked}")
    note = crm.load(found[0].path)
    edits.add_items(note, "emails", [address])
    return [c for c in [crm.save(note)] if c]


def _asked_whether_one(crm, review, address, person, holder):
    """Another person's note has the address the owner said is this person's (only people hold addresses): a
    duplicate review of the two, whose yes merges them and lets the address follow. What it says, for the problem the
    owner sees."""
    other = crm.entity(holder)
    asked = reviews.propose(
        crm,
        "duplicate",
        f"Is {other.link} the same person as {person.link}?",
        [person.link, other.link],
        [f"You answered yes to {review.link}: {address} is {person.name}'s, and {other.link} has it."],
        [],
        review.link,
    )
    if asked.get("decision", "pending") == "pending":
        return f": {schema.link(asked['name'])} asks whether they are one"
    return f": you answered {asked['decision']} in {schema.link(asked['name'])}"


def _change_job(crm, review, found):
    if (pair := reviews.job_change(found)) is None:
        return None
    person, org = pair
    note = crm.load(person.path)
    old = note.fields.get("org")
    if isinstance(old, str) and names.file_key(schema.link_target(old) or "") == names.file_key(org.name):
        return []
    edits.set_value(note, "org", org.link, review.link, crm.today())
    if isinstance(old, str) and old.strip():
        edits.add_items(note, "former_orgs", [old])
    return [c for c in [crm.save(note)] if c]


ACTS = {"address": _add_address, "job_change": _change_job}  # reviews whose yes changes a note, once
DONE = {"address": "add the address", "job_change": "change the organization"}


def _decide_duplicate(crm, review, decision, changes):
    decision = DUPLICATE_ANSWERS.get(decision)
    if review.fields.get("kind") != "duplicate" or decision is None:
        return
    try:
        pair = [crm.find(c) for c in edits.listed(review.fields.get("candidates"))]
        if len(pair) != 2 or pair[0].type != pair[1].type or pair[0].type not in PLURALS:
            return
        if pair[0].path == pair[1].path:  # merged already, as another review of the two asked
            return
        if decision == "different":
            changes.extend(_different(crm, review, pair))
        else:
            if said := _said_different(crm, review, pair):
                raise OrbitError(f"you answered different in {said.link}: set the one that doesn't hold to what does")
            keep, drop = sorted(pair, key=lambda e: (e.fields.get("me") is not True, (e.id or "").partition("_")[2]))
            changes.extend(merge(crm, keep.link, drop.link, review.link, overrule=True)["changed"])
    except OrbitError as e:
        done = "merge them" if decision == "same" else "record it"
        crm.review_problems[review.path] = f"decided {decision}, but orbit couldn't {done}: {e}"


def _said_different(crm, review, pair):
    """Another duplicate review of the two that the owner answered different, if any."""
    asked = {names.file_key(e.name) for e in pair}
    for other in crm.entities(REVIEW):
        candidates = {names.file_key(schema.link_target(c) or "") for c in edits.listed(other.fields.get("candidates"))}
        decision = other.fields.get("decision")
        answered = isinstance(decision, str) and DUPLICATE_ANSWERS.get(decision) == "different"
        if answered and other.path != review.path and other.fields.get("kind") == "duplicate" and candidates == asked:
            return other
    return None


def _different(crm, review, pair):
    notes = [crm.load(e.path) for e in pair]  # both first, so a gone one changes neither
    for note, other in zip(notes, pair[::-1]):
        edits.add_items(note, "distinct_from", [other.link])
        if note.fields.get("review_status") == "needs_review":
            edits.set_value(note, "review_status", "confirmed", review.link, crm.today())
    return [c for c in map(crm.save, notes) if c]


def link_by_domain(crm, dry_run=False):
    """Link every person without an organization, but the owner, to the one their address is at (see
    resolve.organization_of), with a history line that names the address, dated when the address was last in use
    (their last contact, else today): so that an email from after that still changes the organization. What was
    linked, or would be."""
    found, changes, unreadable = [], Changes(), []
    for person in crm.entities(schema.PERSON):
        if person.fields.get("me") or person.fields.get("org") not in (None, ""):
            continue
        emails = [e for e in edits.listed(person.fields.get("emails")) if isinstance(e, str)]
        at = next(((e, org) for e in emails if (org := resolve.organization_of(crm, e))), None)
        if at is None:
            continue
        if not dry_run:
            try:
                note = crm.load(person.path)
            except OrbitError as e:
                unreadable.append(_left(crm, person.path, e))
                continue
            last = str(note.fields.get("last_contact") or "")
            edits.set_value(
                note, "org", at[1].link, f"the address {at[0]}", last if schema.is_date(last) else crm.today()
            )
            changes.add(crm.save(note))
        found.append({"person": person.link, "org": at[1].link, "address": at[0]})
    return {"dry_run": dry_run, "linked": found, "unreadable": unreadable, "changed": list(changes)}


def create_missing_references(crm, dry_run=False):
    """Give every link to a note that doesn't exist one: the note whose alias it names, if exactly one has it, or a
    stub of the type the linking field asks for. Links whose type can't be told are left, with the reason; links to
    files that aren't notes, there or not, are lint_vault's."""
    rows = crm.index.db.execute(
        """SELECT l.target, l.target_key, l.field, n.type, n.name FROM links l JOIN notes n ON n.path = l.path
           WHERE l.target_key NOT IN (SELECT value FROM claims WHERE kind = 'name') ORDER BY l.target_key, n.path"""
    ).fetchall()
    files = crm.vault.link_keys()
    missing = {}
    for row in rows:
        if not PurePosixPath(row["target"]).suffix and row["target_key"] not in files:
            missing.setdefault(row["target_key"], []).append(row)
    aliases = _aliases(crm)
    found = {"dry_run": dry_run, "created": [], "mapped": [], "skipped": []}
    changes, left = Changes(), []
    for key, links in missing.items():
        target, notes = links[0]["target"], sorted({r["name"] for r in links})
        owners = aliases.get(key, [])
        if len(owners) == 1:
            found["mapped"].append({"link": schema.link(target), "to": owners[0].link, "notes": len(notes)})
            if not dry_run:
                left += relink(crm, target, owners[0].name, changes)
            continue
        if owners:
            alternatives = " and ".join(o.link for o in owners)
            found["skipped"].append(
                {"link": schema.link(target), "reason": f"an alias of {alternatives}; link one of them"}
            )
            continue
        types = sorted({t for r in links for t in _linked_as(r)})
        if len(types) != 1 or types[0] not in schema.ENTITY:
            reason = (
                f"linked as {' and as '.join(map(console.an, types))}"
                if types
                else "only linked in text, so its type is unknown"
            )
            found["skipped"].append({"link": schema.link(target), "reason": f"{reason}; create it with upsert_*"})
            continue
        stub = {"link": schema.link(target), "type": types[0], "name": names.file_name(target)}
        if not dry_run:
            count = f"{len(notes)} note{'' if len(notes) == 1 else 's'}"
            reason = f"a stub for the links to it from {count}"
            note = writes.new_entity(crm, types[0], {"name": target}, schema.link(notes[0]), crm.today(), reason, True)
            stub |= {"id": note.fields["id"], "path": changes.add(crm.save(note, created=True))["path"]}
            if note.name != target:
                left += relink(crm, target, note.name, changes)
        found["created"].append(stub)
    return found | {"links_left": list({n["path"]: n for n in left}.values()), "changed": list(changes)}


def _aliases(crm):
    """The people, organizations and topics each alias names, by the alias as links compare it."""
    found = {}
    for kind in schema.ENTITY:
        for entity in crm.entities(kind):
            for alias in {names.file_key(a) for a in edits.listed(entity.fields.get("aliases")) if isinstance(a, str)}:
                found.setdefault(alias, []).append(entity)
    return {k: sorted(v, key=lambda e: e.name) for k, v in found.items()}


def _linked_as(row):
    """The type a link asks for: that of the front-matter field holding it, if the field leads to one type."""
    spec = schema.TYPES.get(row["type"])
    field = spec.field(row["field"]) if spec and row["field"] else None
    return field.to if field and field.kind == "link" and len(field.to) == 1 else ()


def _result(crm, found, path, changes):
    return {
        "id": found.id,
        "name": PurePosixPath(path).stem,
        "path": str(crm.vault.path(path)),
        "changed": list(changes),
    }
