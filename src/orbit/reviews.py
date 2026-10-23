"""Reviews: questions for the vault's owner, as notes in 90_Review, each with one question, the evidence for and
against, and how to answer. The owner answers in Obsidian by setting `decision`, or, for an open question, in their own
words in its `answer` property; `upkeep.apply_reviews` applies the answers that change notes: duplicates
merged or recorded as different, an address added, a job change made, an open question marked answered. What an agent
then does with an answer, it records with `settle`."""

from . import console, edits, names, schema
from .entries import SEP
from .errors import OrbitError

LABELS = {
    "duplicate": "Duplicate",
    "job_change": "Job change",
    "address": "Address",
    "other": "Question",
    "question": "Open question",
}
PLURALS = {schema.PERSON: "people", schema.ORGANIZATION: "organizations", schema.TOPIC: "topics"}
ANSWERS = {
    "duplicate": "Set `decision` to `same` or `different`. orbit then merges the two notes, or records them as "
    "different {plural}.",
    "job_change": "Set `decision` to `yes` or `no`.",
    "job_change_applied": "Set `decision` to `yes` or `no`. On yes, orbit makes {org} the organization of {person}, "
    "and the one before a former one.",
    "address": "Set `decision` to `yes` or `no`. On yes, orbit then adds {address} to the emails of {person}.",
    "other": "Set `decision` to `yes` or `no`.",
    "question": "Write your answer in its `answer` property, in your own words: in the Review base's table, or in the "
    "note's properties. Leave `decision` as it is: orbit marks the question answered, and the next agent that reads "
    "it records what follows and says so under ## Applied.",
}


def propose(crm, kind, question, candidates, evidence_for, evidence_against, source, address=None):
    """Write a review note with one question for the owner, answered yes or no, or for an open question in words; or
    return the pending one that asks it already."""
    if kind not in LABELS:
        raise OrbitError(f"kind: one of {', '.join(LABELS)}")
    if not isinstance(question, str) or not question.strip():
        raise OrbitError("question: the one question the owner should answer")
    found = list({e.path: e for e in (crm.find(c, role="candidates") for c in edits.listed(candidates))}.values())
    if kind == "duplicate" and (len(found) != 2 or found[0].type != found[1].type or found[0].type not in PLURALS):
        raise OrbitError("candidates: a duplicate review asks about two people, two organizations or two topics")
    if not found:
        raise OrbitError("candidates: the notes the question is about")
    address = _address(crm, found, address) if kind == "address" else None
    link, date = crm.source(source)
    links = [e.link for e in found]
    asked = {names.file_key(e.name) for e in found}
    for existing in crm.entities(schema.REVIEW):
        candidates = {
            names.file_key(schema.link_target(c) or "") for c in edits.listed(existing.fields.get("candidates"))
        }
        same = existing.fields.get("kind") == kind and candidates == asked and existing.fields.get("address") == address
        if existing.fields.get("decision") == "pending" and same:
            return {
                "id": existing.id,
                "path": str(crm.vault.path(existing.path)),
                "name": existing.name,
                "existing": True,
            }
    who = [e.name for e in found]
    title = f"{date} {LABELS[kind]} – {' and '.join([', '.join(who[:-1]), who[-1]] if len(who) > 1 else who)}"
    fields = {"kind": kind, "question": question.strip(), "candidates": links, "decision": "pending", "source": link}
    fields |= {"address": address} if address else {}
    fields |= {"answer": ""} if kind == "question" else {}  # a cell to type into, in the Review base's table
    sections = [
        ("Evidence for", _points(evidence_for)),
        ("Evidence against", _points(evidence_against)),
        ("How to answer", [_answer(kind, found, address)]),
    ]
    note = crm.new(schema.REVIEW, schema.TYPES[schema.REVIEW].folder, title, fields, sections)
    change = crm.save(note, created=True)
    return {"id": change["id"], "path": change["path"], "name": change["name"], "existing": False, "changed": [change]}


def answer(note):
    """The owner's words to an open question, in its `answer` property; "" if none."""
    given = note.fields.get("answer")
    return given.strip() if isinstance(given, str) else ""


def settle(crm, review, done, source):
    """Record what was done with the owner's answer to a review: under `## Applied`, and as its `applied` date, once."""
    found = crm.find(review, role="review")
    if found.type != schema.REVIEW:
        raise OrbitError(f"review: {found.name} is {console.an(found.type)}, not a review")
    if not isinstance(done, str) or not done.strip():
        raise OrbitError("done: what was done with the answer, in a line, e.g. 'Recorded the account on Me'")
    if found.fields.get("decision") in (None, "pending"):
        raise OrbitError(f"review: {found.link} is not answered yet: leave it to the owner")
    result = {"id": found.id, "name": found.name, "path": str(crm.vault.path(found.path))}
    if found.fields.get("applied"):
        return result | {"existing": True, "changed": []}
    link, _ = crm.source(source)
    note = crm.load(found.path)
    today = crm.today()
    note.fields["applied"] = today
    line = SEP.join([f"- {today}", " ".join(done.split()), link])
    note.body.append("Applied", [line], schema.TYPES[schema.REVIEW].sections)
    return result | {"existing": False, "changed": [crm.save(note)]}


def job_change(found):
    """The person and the organization a job change is about, if it names one of each; else None."""
    by_type = {e.type: e for e in found}
    pair = (by_type.get(schema.PERSON), by_type.get(schema.ORGANIZATION))
    return pair if len(found) == 2 and all(pair) else None


def _address(crm, found, address):
    """The address an address review asks about, checked: one person's, not theirs yet."""
    if not isinstance(address, str) or not address.strip():
        raise OrbitError("address: the address the question is about")
    if len(found) != 1 or found[0].type != schema.PERSON:
        raise OrbitError("candidates: an address review asks about one person")
    address = schema.clean(schema.PERSON, "emails", [address])[0]
    if names.is_role_address(address, crm.vault.config.role_addresses):
        raise OrbitError(f"address: {address} is a role address, which belongs to no person")
    if address in [names.email(e) for e in edits.listed(found[0].fields.get("emails")) if isinstance(e, str)]:
        raise OrbitError(f"address: {address} is one of {found[0].link}'s already")
    return address


def _answer(kind, found, address):
    if kind == "address":
        return ANSWERS[kind].format(address=address, person=found[0].link)
    if kind == "job_change" and (pair := job_change(found)):
        return ANSWERS["job_change_applied"].format(person=pair[0].link, org=pair[1].link)
    return ANSWERS[kind].format(plural=PLURALS.get(found[0].type, ""))


def _points(evidence):
    """Evidence as list items, one line each, so no point can break the note's sections."""
    return [f"- {' '.join(str(e).split())}" for e in edits.listed(evidence) if str(e).strip()]
