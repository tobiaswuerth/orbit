"""resolve_entity: the people, organizations or topics a description may mean, ranked, each with the evidence for it.
orbit finds candidates; the caller decides whether one is the same.

Scores run from 0 to 1. An exact email address, phone number, domain or company UID scores highest; a name in any word
order, case or spelling of umlauts next; initials, nicknames, part of a name and names that sound alike less. A
matching company domain, organization or job title adds to a score but never makes a candidate on its own.
"""

from . import edits, names, schema
from .errors import OrbitError

RESOLVABLE = (schema.PERSON, schema.ORGANIZATION, schema.TOPIC)
LIMIT = 5
TOP = 0.95  # the highest score a candidate gets without an exact address, phone number, domain or UID


def resolve(
    crm, type, names_=(), emails=(), domain=None, org=None, job_title=None, phone=None, uid_che=None, limit=LIMIT
):
    if type not in RESOLVABLE:
        raise OrbitError(f"type: one of {', '.join(RESOLVABLE)}")
    names_ = [n.strip() for n in names_ or [] if isinstance(n, str) and n.strip()]
    emails = [names.address(e) or names.email(e) for e in emails or [] if isinstance(e, str) and e.strip()]
    if bad := [e for e in emails if not names.is_email(e)]:
        raise OrbitError(f"emails: {bad[0]!r} is not an email address")
    if not (names_ or emails or domain or phone or uid_che):
        raise OrbitError("give at least one of names, emails, domain, phone or uid_che to look for")
    config, notes = crm.vault.config, []
    roles = [e for e in emails if names.is_role_address(e, config.role_addresses)]
    if roles and type == schema.PERSON:
        notes.append(f"{', '.join(roles)}: role addresses belong to no person, so they were not looked for")
    domains = {names.normalize_domain(domain)} if domain else set()
    domains |= {names.domain(e) for e in emails}
    if free := sorted(d for d in domains if d in config.free_mail_domains):
        notes.append(f"{', '.join(free)}: free-mail domains say nothing about an employer")
    query = {
        "names": names_,
        "emails": [e for e in emails if e not in roles] if type == schema.PERSON else emails,
        "domains": domains - set(free),
        "org": org,
        "job_title": job_title,
        "phone": names.phone_key(phone) if phone else None,
        "uid": schema.uid(uid_che) if uid_che else None,
    }
    score = {schema.PERSON: _person, schema.ORGANIZATION: _organization, schema.TOPIC: _topic}[type]
    found = []
    for path in _candidates(crm, type, query):
        entity = crm.entity(path)
        if entity.type == type and (match := score(crm, entity, query)):
            found.append((match, entity))
    found.sort(key=lambda m: (-m[0][0], m[1].name))
    if not found:
        notes.append(f'no candidate: if this is a new {type}, create it with match "new"')
    return {"candidates": [_context(crm, e, s, r) for (s, r), e in found[: max(1, limit)]], "notes": notes}


def _candidates(crm, type, query):
    """The paths worth scoring: those sharing an identifier with the query."""
    pairs = [("email", e) for e in query["emails"]] + [("domain", d) for d in query["domains"]]
    if (
        type == schema.ORGANIZATION
    ):  # an address at a subdomain is the organization's too: students.school.example, school.example
        pairs += [("domain", p) for d in query["domains"] for p in names.parent_domains(d)]
    pairs += [("phone", query["phone"])] if query["phone"] else []
    pairs += [("uid", query["uid"])] if query["uid"] else []
    nicknames = crm.vault.nicknames
    for written in query["names"] + [e.partition("@")[0] for e in query["emails"]]:
        parts = names.parse_name(written)
        key = names.org_key(written)
        pairs += [("key", parts.key), ("org", key), ("title", names.fold(written))]
        pairs += [("initials", key), ("token", names.initials(key))]  # AZO, Ausbildungszentrum Zürcher Oberland
        pairs += [("token", v) for w in parts.full for v in nicknames.variants(w)]
        pairs += [("token", w) for w in names.words(written)]
        pairs += [("sound", names.koelner(parts.surname))] if parts.surname else []
    if type == schema.PERSON and query["org"]:
        pairs += [("org", names.org_key(query["org"]))]
    return crm.index.lookup(pairs)


def _person(crm, entity, query):
    fields, reasons, best = entity.fields, [], 0.0
    emails = [names.email(e) for e in edits.listed(fields.get("emails")) if isinstance(e, str)]
    if hits := sorted(set(emails) & set(query["emails"])):
        best, reasons = 1.0, [f"same email address {', '.join(hits)}"]
    phones = {names.phone_key(p) for p in edits.listed(fields.get("phones")) if isinstance(p, str)}
    if query["phone"] and query["phone"] in phones:
        best = max(best, 0.9)
        reasons.append("same phone number")
    variants, nicknames = _variants(entity), crm.vault.nicknames
    for written in query["names"]:
        if match := _best(names.parse_name(written), variants, nicknames):
            best = max(best, match[0])
            reasons.append(f"{match[1]}: {written}")
    for address in query["emails"]:
        if address not in emails and (match := _best(_address_name(address), variants, nicknames)):
            best = max(best, min(match[0], 0.5))
            reasons.append(f"{match[1]} in the address {address}")
    if not best:
        return None
    boost = 0.0
    theirs = {names.domain(e) for e in emails} | set(_org_domains(crm, fields.get("org")))
    if shared := sorted(theirs & query["domains"]):
        boost += 0.15
        reasons.append(f"same company domain {', '.join(shared)}")
    target = schema.link_target(fields.get("org"))
    if query["org"] and target and names.org_key(target) == names.org_key(query["org"]):
        boost += 0.1
        reasons.append(f"works at {target}")
    if query["job_title"] and names.fold(query["job_title"]) == names.fold(str(fields.get("job_title", ""))):
        boost += 0.05
        reasons.append("same job title")
    return min(best + boost, max(best, TOP)), reasons


def _variants(entity):
    """A note's name and aliases, as ("name" or "alias", text) pairs; items a hand edit left empty are passed over."""
    texts = lambda value: [v for v in edits.listed(value) if isinstance(v, str) and v.strip()]  # noqa: E731
    return [("name", n) for n in texts(entity.fields.get("name"))[:1] or [entity.name]] + [
        ("alias", a) for a in texts(entity.fields.get("aliases"))
    ]


def _best(query, variants, nicknames):
    """The best (score, reason) of a name against a note's name and aliases, or None."""
    matches = []
    for kind, written in variants:
        if match := _name(query, names.parse_name(written), nicknames):
            matches.append((match[0], f"{match[1]} ({kind})"))
    return max(matches, default=None)


def _name(q, c, nicknames):
    """How well a name in parts matches another: (score, reason) or None."""
    if not q.full and not q.initials:
        return None
    if q.full and not q.initials and q.key == c.key:
        return (0.85 if len(q.full) > 1 else 0.55), "same name"
    left, nickname = list(c.full), False
    for word in q.full:
        match = word if word in left else next((w for w in left if w in nicknames.variants(word)), None)
        if match is None:
            return _sound(q, c, nicknames)
        left.remove(match)
        nickname |= match != word
    for initial in q.initials:
        match = next((w for w in left if w.startswith(initial)), None)
        if match is None:
            return _sound(q, c, nicknames)
        left.remove(match)
    whole = not left
    if q.initials:
        return (0.7 if whole and q.full else 0.4), "initials"
    if nickname:
        return (0.65 if whole and len(q.full) > 1 else 0.45), "nickname"
    return 0.35, "part of the name"


def _sound(q, c, nicknames):
    """Names whose surnames sound alike (Kölner Phonetik): a candidate only, since the codes over-match."""
    if not (
        q.surname and c.surname and q.surname != c.surname and names.koelner(q.surname) == names.koelner(c.surname)
    ):
        return None
    given_q = [w for w in q.full if w != q.surname]
    given_c = [w for w in c.full if w != c.surname]
    fits = all(any(g == h or h in nicknames.variants(g) for h in given_c) for g in given_q)
    fits &= all(any(h.startswith(i) for h in given_c) for i in q.initials)
    if not (given_q or q.initials):
        return 0.25, "sounds alike"
    return (0.5, "sounds alike") if fits else None


def _address_name(address):
    """An address's local part read as a name: hansi.mueller → Hansi Mueller, h.mueller → H. Mueller."""
    words = names.email_tokens(address)
    full = tuple(w for w in words if len(w) > 1)
    return names.Name(full, tuple(w for w in words if len(w) == 1), full[-1] if full else None)


def organization_of(crm, address):
    """The organization an address is at: the one whose domains hold its domain, or else the nearest domain it is
    under. None for a free-mail domain, and where no organization or several claim it."""
    domain = names.domain(names.email(address))
    if domain in crm.vault.config.free_mail_domains:
        return None
    for claimed in [domain, *names.parent_domains(domain)]:
        found = [e for e in map(crm.entity, crm.index.lookup([("domain", claimed)])) if e.type == schema.ORGANIZATION]
        if found:
            return found[0] if len(found) == 1 else None
    return None


def _org_domains(crm, org):
    target = schema.link_target(org) if isinstance(org, str) else None
    if not target:
        return []
    path = crm.index.holder("name", names.file_key(target))
    domains = edits.listed(crm.entity(path).fields.get("domains")) if path else []
    return [names.normalize_domain(d) for d in domains if isinstance(d, str)]


def _organization(crm, entity, query):
    fields, reasons, best = entity.fields, [], 0.0
    if query["uid"] and schema.uid(str(fields.get("uid_che", ""))) == query["uid"]:
        best = 1.0
        reasons.append(f"same company UID {query['uid']}")
    domains = {names.normalize_domain(d) for d in edits.listed(fields.get("domains")) if isinstance(d, str)}
    if shared := sorted(domains & query["domains"]):
        best = max(best, 0.95)
        reasons.append(f"same domain {', '.join(shared)}")
    elif under := sorted(domains & {p for d in query["domains"] for p in names.parent_domains(d)}):
        best = max(best, 0.9)
        reasons.append(f"a subdomain of {', '.join(under)}")
    for written in query["names"]:
        for kind, v in _variants(entity):
            ours, theirs = names.org_key(written).split(), names.org_key(v).split()
            if names.fold(written) == names.fold(v):
                best = max(best, 0.9)
                reasons.append(f"same name ({kind}): {written}")
            elif ours == theirs:
                best = max(best, 0.85)
                reasons.append(f"same name without legal form ({kind}): {written}")
            elif _leads(ours, theirs) or _leads(theirs, ours):
                best = max(best, 0.75)
                reasons.append(f"one name starts with the other ({kind}): {written}")
            elif _initials(ours, theirs) or _initials(theirs, ours):
                best = max(best, 0.75)
                reasons.append(f"one name is the other's initials ({kind}): {written}")
            elif set(ours) <= set(theirs):
                best = max(best, 0.4)
                reasons.append(f"part of the name ({kind}): {written}")
    return (best, reasons) if best else None


def _leads(short, long):
    """Whether the words of one name are the first words of a longer one: Acme, Acme Services."""
    return 0 < len(short) < len(long) and long[: len(short)] == short


def _initials(short, long):
    """Whether a one-word name is the initials of a longer one: AZO, Ausbildungszentrum Zürcher Oberland."""
    return len(short) == 1 and len(long) > 1 and short[0] == names.initials(" ".join(long))


def _topic(crm, entity, query):
    reasons, best = [], 0.0
    for written in query["names"]:
        for kind, v in _variants(entity):
            ours, theirs = set(names.words(written)), set(names.words(v))
            shared = len(ours & theirs) / len(ours | theirs) if ours | theirs else 0
            if names.fold(written) == names.fold(v):
                best = max(best, 0.9)
                reasons.append(f"same name ({kind}): {written}")
            elif shared >= 0.5:
                best = max(best, round(0.5 + 0.4 * shared, 2))
                reasons.append(f"most words alike ({kind}): {written}")
            elif ours <= theirs:
                best = max(best, 0.4)
                reasons.append(f"part of the name ({kind}): {written}")
    return (best, reasons) if best else None


def _context(crm, entity, score, reasons):
    """A candidate as the caller sees it: enough to decide, without reading the note."""
    keys = {
        schema.PERSON: ("org", "job_title", "emails", "last_contact", "review_status", "distinct_from", "me"),
        schema.ORGANIZATION: ("domains", "location", "relationship", "distinct_from"),
        schema.TOPIC: ("status", "orgs", "people"),
    }[entity.type]
    found = {"id": entity.id, "name": entity.name, "path": str(crm.vault.path(entity.path)), "score": round(score, 2)}
    found["reasons"] = list(dict.fromkeys(reasons))
    return found | {k: entity.fields[k] for k in keys if entity.fields.get(k) not in (None, [], "")}
