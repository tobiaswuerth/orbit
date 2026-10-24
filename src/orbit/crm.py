"""A vault opened for work: its index, kept up to date with the notes; the lock that makes this process the vault's
one writer; and what every tool needs to read and write notes safely.

Every write follows the same order: check the index, read the note again (an edit made by hand may not be indexed
yet), write it atomically, and bring the index up to date in the same call. If orbit dies in between, the next sync
mends the index.
"""

import datetime
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from filelock import FileLock, Timeout

from . import console, edits, entries, ids, index, names, schema, settings, upkeep
from .errors import OrbitError, VaultInUse
from .frontmatter import FrontMatterError
from .index import Index
from .sections import Body, build
from .vault import CONFIG, NICKNAMES, Note, Vault, is_hidden, is_note_path

SYSTEM_FILES = {CONFIG, NICKNAMES}
# Where a note of each type belongs among the links of an interaction or a topic, for a caller who named it elsewhere
WHERE = {schema.ORGANIZATION: "orgs", schema.TOPIC: "topics", schema.PERSON: "from, to, cc, participants or mentioned"}
RELATIONS = {"from", "to", "cc", "participants", "mentioned", "sender", "people", "orgs", "topics"}
REFERENCE = (
    "an id such as per_01M4WNN540CGMAHYXV1R90AA5V, a note's name as links write it, such as Hans Müller, or a "
    "person's email address"
)


@dataclass(frozen=True)
class Entity:
    """A note as the index knows it."""

    path: str
    id: str | None
    type: str | None
    name: str
    fields: dict

    @property
    def link(self):
        return schema.link(self.name)


class Crm:
    def __init__(self, root, home=None, now=None):
        """Open the vault at `root`, with its index under `home` (default: ORBIT_HOME). `now` gives the current time,
        as an aware datetime; the tests fix it."""
        self.vault = Vault(root)
        if not self.vault.path(CONFIG).is_file():
            raise OrbitError(f"{self.vault.root} is not an orbit vault: it has no {CONFIG}. Run `orbit init` first.")
        self.vault.config  # noqa: B018 - a broken orbit.toml fails here, before anything else
        path = index.location(self.vault.root, Path(home) if home else settings.current().home)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = FileLock(path.with_suffix(".lock"), timeout=0)
        try:
            self._lock.acquire()
        except Timeout:
            raise VaultInUse(
                f"another orbit process is using {self.vault.root}; stop it first, or work through its tools"
            ) from None
        try:
            self.index = Index(self.vault, path)
        except BaseException:
            self._lock.release()
            raise
        self.now = now or (lambda: datetime.datetime.now().astimezone())
        self.review_problems = {}  # review path: why its decision couldn't be applied

    def close(self):
        self.index.close()
        self._lock.release()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def today(self):
        return self.now().date().isoformat()

    def refresh(self, paths=None):
        """Bring the index up to date with every note, or with the files at these vault paths, which may have changed,
        appeared or gone, and apply the decisions the owner set on reviews and the tasks' Cancel boxes. A change to
        orbit.toml or nicknames.txt is read, and a change to anything that may be a folder brings on a full sync."""
        if paths is None:
            report = self.index.sync()
        else:
            paths = set(paths)
            if paths & SYSTEM_FILES:
                self.vault.reload()
            others = {p for p in paths - SYSTEM_FILES if not is_note_path(p) and not is_hidden(p)}
            if any(not PurePosixPath(p).suffix for p in others):
                report = self.index.sync()
            else:
                report = self.index.refresh(p for p in paths if is_note_path(p))
        touched = report.added + report.changed
        if paths is None or any(p.startswith(schema.TYPES[schema.REVIEW].folder) for p in touched):
            upkeep.apply_reviews(self)
        tasks = [p for p in touched if p.startswith(schema.TYPES[schema.TASK].folder)]
        if paths is None or tasks:
            upkeep.apply_task_boxes(self, None if paths is None else set(tasks))
        return report

    # Finding notes

    def entity(self, path):
        return self.entity_of(self.index.row(path))

    @staticmethod
    def entity_of(row):
        """The Entity of an index row."""
        return Entity(row["path"], row["id"], row["type"], row["name"], json.loads(row["fields"]))

    def entities(self, type_name):
        """Every note of a type, in path order."""
        return [self.entity_of(row) for row in self.index.rows(type_name)]

    def find(self, ref, types=None, role="note", relation=None):
        """The note a reference names: its id, its name as links write it, with or without [[ ]], or, for a person,
        an email address; or the one note whose name field or an alias it is. `types`, if given, are the types it may
        have; `role` names what it is for, in errors, and `relation` the link it is for, if `role` doesn't."""
        if not isinstance(ref, str) or not ref.strip():
            raise OrbitError(f"{role}: give {REFERENCE}")
        ref = ref.strip()
        target = schema.link_target(ref) or ref
        if address := names.address(target):
            if names.is_role_address(address, self.vault.config.role_addresses):
                raise OrbitError(
                    f"{role}: {address} is a role address, which belongs to no person; leave it out, or name its "
                    "organization where an organization belongs"
                )
            path = self.index.holder("email", address)
            if path is None:
                raise OrbitError(f"{role}: no person has the address {address}; create them with upsert_person first")
        elif ids.is_valid(ref):
            path = self.index.holder("id", ref)
        else:
            path = self.index.holder("name", names.file_key(target.rsplit("/", 1)[-1].removesuffix(".md")))
            path = path or self._named(target, role)
        if path is None:
            raise OrbitError(
                f"{role}: no note has the id or name {ref!r}. Find it with resolve_entity or search_entities, or "
                "create it first."
            )
        found = self.entity(path)
        if types and found.type not in types:
            kinds = " or ".join(map(console.an, types))
            belongs = (
                f": name it under {WHERE[found.type]}"
                if found.type in WHERE and (relation or role) in RELATIONS
                else ""
            )
            raise OrbitError(
                f"{role}: {found.link} is {console.an(found.type or 'note of no type')}, not {kinds}{belongs}"
            )
        return found

    def _named(self, target, role):
        """The path of the one note whose `name` field or an alias is `target`, as Me.md's is the owner's name; None
        if no note's is."""
        key = names.fold(target)
        pairs = [("key", names.parse_name(target).key), ("org", names.org_key(target)), ("title", key)]
        named = []
        for path in self.index.lookup(pairs):
            fields = self.entity(path).fields
            written = [fields.get("name"), *edits.listed(fields.get("aliases"))]
            if any(isinstance(w, str) and names.fold(w) == key for w in written):
                named.append(path)
        if len(named) > 1:
            listed = " and ".join(self.entity(path).link for path in sorted(named))
            raise OrbitError(f"{role}: {target!r} is the name or an alias of {listed}; give the one you mean by its id")
        return named[0] if named else None

    def links(self, refs, types=None, role="note"):
        """Wikilinks to the notes these references name, without repeats."""
        refs = [refs] if isinstance(refs, str) else refs or []
        return list(dict.fromkeys(self.find(ref, types, role).link for ref in refs))

    def source(self, source):
        """A source as notes record it, and its date: a link to the note the source names by id or [[link]], or to
        the interaction logged from the file it names, dated like that note if it is an interaction; or else the text,
        dated today."""
        if not isinstance(source, str) or not source.strip():
            raise OrbitError(
                "source: give the id of the interaction the facts come from, or a short description such as "
                '"the owner in chat, 2026-10-22"'
            )
        source = source.strip()
        if ids.is_valid(source) or schema.link_target(source):
            found = self.find(source, role="source")
        elif logged := self.index.lookup([("source_file", names.path_key(source))]):
            found = self.entity(logged[0])  # the file an interaction was logged from: that interaction
        elif names.local_path(source):
            raise OrbitError(
                f"source: {source} is a file no interaction was logged from: log the interaction first, with this "
                "file as its source_file, and give its id"
            )
        else:
            return entries.text(source), self.today()
        date = found.fields.get("date") if found.type == schema.INTERACTION else None
        return found.link, (date[:10] if isinstance(date, str) and schema.is_date(date[:10]) else self.today())

    # Reading and writing notes

    def load(self, path):
        """A note read again from its file, with the index brought up to date with it first."""
        self.index.refresh([path])
        if self.index.row(path) is None:
            raise OrbitError(f"{path} is gone from the vault; find the note again")
        try:
            return self.vault.note(path)
        except (FrontMatterError, UnicodeDecodeError) as e:
            reason = e if isinstance(e, FrontMatterError) else "it isn't UTF-8 text"
            raise OrbitError(f"{path} can't be read: {reason}; fix it by hand (lint_vault lists such notes)") from None

    def new(self, type_name, folder, name, fields, sections, distinguisher=None):
        """A new note of a type with a new id, under a file name no other note has: `name`, or else `name
        (distinguisher)`, or else `name (2)`, `name (3)`, …, each after `name` is made a safe file name, so that
        shortening a long one never cuts off what tells them apart."""
        base = names.file_name(name)
        stems = (
            [base]
            + ([f"{base} ({names.file_name(distinguisher)})"] if distinguisher else [])
            + [f"{base} ({n})" for n in range(2, 1000)]
        )

        def free(stem):
            taken = self.index.holder("name", names.file_key(stem))
            return taken is None and not self.vault.path(f"{folder}/{stem}.md").exists()

        stem = next((s for s in stems if free(s)), None)
        if stem is None:
            raise OrbitError(f"too many notes are called {name}; give a more distinctive name")
        path = f"{folder}/{stem}.md"
        spec, today = schema.TYPES[type_name], self.today()
        fields = {"type": type_name, "id": ids.new(spec.prefix, self.now())} | fields | {"created": today}
        if spec.field("updated"):
            fields["updated"] = today
        return Note(path, schema.order(type_name, fields), Body.parse(build(sections)))

    def save(self, note, created=False):
        """Write a note if it changed, setting its `updated` date, and index it. What changed, for the caller: the
        note's id, type, name and absolute path, and whether it was created or updated; None if nothing changed."""
        if not created:
            before = self.vault.read(note.path).decode("utf-8").removeprefix("\ufeff").replace("\r\n", "\n")
            if note.text() == before:
                return None
            if note.type and schema.TYPES[note.type].field("updated"):
                note.fields["updated"] = self.today()
        self.vault.write(note.path, note.text())
        self.index.refresh([note.path])
        return self.describe(note, "created" if created else "updated")

    def describe(self, note, action):
        """A note as tools report what they changed: its id, type, name, absolute path, and what happened to it."""
        return {
            "id": note.fields.get("id"),
            "type": note.type,
            "name": note.name,
            "path": str(self.vault.path(note.path)),
            "action": action,
        }
