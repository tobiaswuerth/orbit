"""The index: a SQLite database in ORBIT_HOME, derived from a vault's notes alone, that makes lookups fast and
guarantees uniqueness. It can be deleted at any time; `sync` builds it again from the notes.

Its unique indexes guarantee that no two notes share an id or a file name, no two people an email address, and no two
interactions a message id. A note edited by hand that breaks one is indexed all the same: of the notes that claim a
value, the first in path order holds it, the others are recorded as clashes, and `lint_vault` reports them.
"""

import hashlib
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from . import names, schema
from .entries import Change
from .frontmatter import FrontMatterError
from .vault import Note

VERSION = 6  # of the layout below (6: organizations by their initials); an index of another version is built again
UNIQUE = {"id": "id", "name": "file name", "email": "email address", "message_id": "message id"}
LAYOUT = """
CREATE TABLE notes (
    num INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,  -- in the vault, with forward slashes
    id TEXT,
    type TEXT,  -- a known type, or NULL
    name TEXT NOT NULL,  -- the file name without .md: the note's name in links
    mtime_ns INTEGER NOT NULL,
    size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    fields TEXT NOT NULL,  -- the front matter, as JSON
    error TEXT  -- why the note couldn't be read, if it couldn't
);
CREATE INDEX notes_id ON notes(id);
CREATE INDEX notes_type ON notes(type);

-- Values only one note may hold: ids, file names, people's email addresses, message ids.
CREATE TABLE claims (
    kind TEXT NOT NULL,
    value TEXT NOT NULL,
    path TEXT NOT NULL REFERENCES notes(path) ON DELETE CASCADE,
    owner INTEGER NOT NULL,  -- 1 for the note that holds the value; 0 for a clash
    PRIMARY KEY (kind, value, path)
) WITHOUT ROWID;
CREATE UNIQUE INDEX claims_owner ON claims(kind, value) WHERE owner;
CREATE INDEX claims_path ON claims(path);

-- What notes are looked up by: addresses, domains, phone and name keys, sound-alike codes; an email's thread; the
-- file an interaction was logged from.
CREATE TABLE identifiers (
    kind TEXT NOT NULL,
    value TEXT NOT NULL,
    path TEXT NOT NULL REFERENCES notes(path) ON DELETE CASCADE,
    PRIMARY KEY (kind, value, path)
) WITHOUT ROWID;
CREATE INDEX identifiers_path ON identifiers(path);

CREATE TABLE links (
    path TEXT NOT NULL REFERENCES notes(path) ON DELETE CASCADE,
    field TEXT,  -- the front-matter field that holds the link; NULL for a link in the body
    target TEXT NOT NULL,  -- the note it names, as written
    target_key TEXT NOT NULL  -- that name as file names compare
);
CREATE INDEX links_path ON links(path);
CREATE INDEX links_target ON links(target_key);

-- Field changes, from the notes' History sections.
CREATE TABLE changes (
    path TEXT NOT NULL REFERENCES notes(path) ON DELETE CASCADE,
    date TEXT NOT NULL,
    field TEXT NOT NULL,
    old TEXT,
    new TEXT,
    source TEXT NOT NULL
);
CREATE INDEX changes_path ON changes(path, field);

-- Full-text search; each row's rowid is its note's num.
CREATE VIRTUAL TABLE search USING fts5(names, emails, roles, text, tokenize = 'unicode61 remove_diacritics 2');
"""


@dataclass
class Report:
    """What a sync changed in the index."""

    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    def __bool__(self):
        return bool(self.added or self.changed or self.removed)

    def __str__(self):
        return f"{len(self.added):,} added, {len(self.changed):,} changed, {len(self.removed):,} removed"


def location(root, home):
    """Where the index of the vault at `root` lives: one database per vault, under ORBIT_HOME."""
    key = hashlib.sha256(os.path.normcase(str(Path(root).resolve())).encode()).hexdigest()[:12]
    slug = re.sub(r"[^\w.-]+", "-", Path(root).resolve().name).strip("-") or "vault"
    return Path(home) / "indexes" / f"{slug}-{key}.sqlite"


class Index:
    def __init__(self, vault, path):
        self.vault, self.path = vault, Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._open()
        except sqlite3.DatabaseError:  # a damaged file: the index is derived, so it is simply built again
            for suffix in ("", "-wal", "-shm"):
                self.path.with_name(self.path.name + suffix).unlink(missing_ok=True)
            self._open()

    def _open(self):
        self.db = sqlite3.connect(self.path, isolation_level=None)
        try:
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA journal_mode = WAL")
            self.db.execute("PRAGMA synchronous = NORMAL")
            if self.db.execute("PRAGMA user_version").fetchone()[0] != VERSION:
                self._create()
            self.db.execute("PRAGMA foreign_keys = ON")
        except BaseException:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def _create(self):
        """Lay out an empty index, dropping whatever an index of another version held."""
        # Full-text search's own tables go with it.
        tables = self.db.execute(
            r"SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'search\_%' ESCAPE '\'"
        )
        for (table,) in tables.fetchall():
            self.db.execute(f'DROP TABLE IF EXISTS "{table}"')
        self.db.executescript(LAYOUT)
        self.db.execute(f"PRAGMA user_version = {VERSION}")

    def rebuild(self):
        """Build the index from scratch."""
        with self.transaction():
            self.db.execute("PRAGMA defer_foreign_keys = ON")
            for table in ("search", "changes", "links", "identifiers", "claims", "notes"):
                self.db.execute(f"DELETE FROM {table}")
        return self.sync()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")

    def sync(self):
        """Bring the index up to date with every note in the vault: notes whose modification time or size changed are
        read again, and indexed again if their content did."""
        files = self.vault.files()
        known = {
            r["path"]: (r["mtime_ns"], r["size"]) for r in self.db.execute("SELECT path, mtime_ns, size FROM notes")
        }
        report = Report()
        with self.transaction():
            for rel in sorted(known.keys() - files.keys()):
                self._remove(rel)
                report.removed.append(rel)
            for rel, stat in files.items():
                if known.get(rel) != stat:
                    self._update(rel, report, stat)
        return report

    def refresh(self, paths):
        """Bring the index up to date with these notes, which may have changed, appeared or gone."""
        report = Report()
        with self.transaction():
            for rel in sorted(set(paths)):
                self._update(rel, report)
        return report

    def _update(self, rel, report, stat=None):
        """Index a note again if its content changed; `stat` is its (mtime_ns, size), if known already."""
        stat = stat or self.vault.stat(rel)
        row = self.db.execute("SELECT mtime_ns, size, sha256 FROM notes WHERE path = ?", (rel,)).fetchone()
        try:
            data = self.vault.read(rel) if stat else None
        except FileNotFoundError:  # gone since it was listed
            data = None
        if data is None:
            if row:
                self._remove(rel)
                report.removed.append(rel)
            return
        sha = hashlib.sha256(data).hexdigest()
        if row and row["sha256"] == sha:
            self.db.execute("UPDATE notes SET mtime_ns = ?, size = ? WHERE path = ?", (*stat, rel))
            return
        if row:
            self._remove(rel)
        self._insert(rel, data, stat, sha)
        (report.changed if row else report.added).append(rel)

    def _remove(self, rel):
        owned = self.db.execute("SELECT kind, value FROM claims WHERE path = ? AND owner", (rel,)).fetchall()
        self.db.execute("DELETE FROM search WHERE rowid = (SELECT num FROM notes WHERE path = ?)", (rel,))
        self.db.execute("DELETE FROM notes WHERE path = ?", (rel,))
        for kind, value in owned:  # the next note in path order that claims the value now holds it
            self.db.execute(
                """UPDATE claims SET owner = 1 WHERE kind = ? AND value = ?
                   AND path = (SELECT min(path) FROM claims WHERE kind = ? AND value = ?)""",
                (kind, value, kind, value),
            )

    def _insert(self, rel, data, stat, sha):
        note, error = None, None
        try:
            note = Note.parse(rel, data.decode("utf-8"))
        except UnicodeDecodeError:
            error = "not UTF-8 text"
        except FrontMatterError as e:
            error = f"unreadable front matter, {e}"
        fields = (note.fields if note else None) or {}
        kind = fields.get("type") if fields.get("type") in schema.TYPES else None
        note_id = fields.get("id") if isinstance(fields.get("id"), str) and fields.get("id") else None
        name = PurePosixPath(rel).stem
        num = self.db.execute(
            """INSERT INTO notes (path, id, type, name, mtime_ns, size, sha256, fields, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (rel, note_id, kind, name, *stat, sha, json.dumps(fields, ensure_ascii=False), error),
        ).lastrowid
        claims = [("name", names.file_key(name))] + ([("id", note_id)] if note_id else [])
        claims += [("id", i) for i in _strings(fields, "merged_from")]  # a merged note's ids find the one it went into
        if kind == schema.PERSON:
            claims += [("email", names.email(e)) for e in _strings(fields, "emails")]
        if kind == schema.INTERACTION:
            claims += [("message_id", m) for m in _strings(fields, "message_id")]
        for claim in dict.fromkeys(claims):
            self._claim(*claim, rel)
        self.db.executemany(
            "INSERT OR IGNORE INTO identifiers (kind, value, path) VALUES (?, ?, ?)",
            [(k, v, rel) for k, v in sorted(_identifiers(kind, fields, name))],
        )
        links = [(key, t) for key, value in fields.items() for t in _link_targets(value)]
        # A note whose front matter can't be read still links where its text does, so links to it can be followed.
        links += [(None, t) for t in _link_targets(note.body.text() if note else data.decode("utf-8", "replace"))]
        self.db.executemany(
            "INSERT INTO links (path, field, target, target_key) VALUES (?, ?, ?, ?)",
            [(rel, key, target, names.file_key(target)) for key, target in links],
        )
        if note and kind in schema.ENTITY:
            changes = [c for c in map(Change.parse, note.body.lines("History") or []) if c]
            self.db.executemany(
                "INSERT INTO changes (path, date, field, old, new, source) VALUES (?, ?, ?, ?, ?, ?)",
                [(rel, c.date, c.field, c.old, c.new, c.source) for c in changes],
            )
        self.db.execute(
            "INSERT INTO search (rowid, names, emails, roles, text) VALUES (?, ?, ?, ?, ?)",
            (num, *_search_columns(note, fields, name)),
        )

    def _claim(self, kind, value, rel):
        holder = self.db.execute(
            "SELECT path FROM claims WHERE kind = ? AND value = ? AND owner", (kind, value)
        ).fetchone()
        if holder and rel < holder["path"]:
            self.db.execute("UPDATE claims SET owner = 0 WHERE kind = ? AND value = ? AND owner", (kind, value))
        self.db.execute(
            "INSERT INTO claims (kind, value, path, owner) VALUES (?, ?, ?, ?)",
            (kind, value, rel, int(holder is None or rel < holder["path"])),
        )

    # Lookups

    def row(self, rel):
        """The index's row of a note, or None."""
        return self.db.execute("SELECT * FROM notes WHERE path = ?", (rel,)).fetchone()

    def rows(self, type_name):
        """The index's rows of every note of a type, in path order."""
        return self.db.execute("SELECT * FROM notes WHERE type = ? ORDER BY path", (type_name,)).fetchall()

    def lookup(self, pairs):
        """The paths of the notes that have any of these (kind, value) identifiers, in path order."""
        found = set()
        for kind, value in set(pairs):
            found |= {
                r[0]
                for r in self.db.execute("SELECT path FROM identifiers WHERE kind = ? AND value = ?", (kind, value))
            }
        return sorted(found)

    def holder(self, kind, value):
        """The path of the note that holds a unique value (see UNIQUE), or None."""
        row = self.db.execute(
            "SELECT path FROM claims WHERE kind = ? AND value = ? AND owner", (kind, value)
        ).fetchone()
        return row["path"] if row else None

    def clashes(self):
        """Unique values that more than one note claims: kind, value, the clashing note's path, and the holder's."""
        return [
            dict(row)
            for row in self.db.execute(
                """SELECT c.kind, c.value, c.path, h.path AS holder FROM claims c
                   JOIN claims h ON h.kind = c.kind AND h.value = c.value AND h.owner
                   WHERE NOT c.owner ORDER BY c.kind, c.value, c.path"""
            )
        ]

    def counts(self):
        """The number of notes of each type; None counts notes of no known type."""
        return summary(self.db)["notes"]

    def summary(self):
        return summary(self.db)


def read_only(path):
    """A connection that only reads an index, as another process keeps it; None if there is no index yet."""
    if not Path(path).is_file():
        return None
    db = sqlite3.connect(f"{Path(path).as_uri()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def summary(db):
    """What an index holds: notes per type (None for notes of no known type), pending reviews, clashes and notes that
    couldn't be read."""
    one = lambda sql: db.execute(sql).fetchone()[0]  # noqa: E731
    return {
        "notes": dict(sorted(db.execute("SELECT type, count(*) FROM notes GROUP BY type").fetchall(), key=_type_order)),
        "pending_reviews": one(
            "SELECT count(*) FROM notes WHERE type = 'review' AND json_extract(fields, '$.decision') = 'pending'"
        ),
        "clashes": one("SELECT count(*) FROM claims WHERE NOT owner"),
        "unreadable": one("SELECT count(*) FROM notes WHERE error IS NOT NULL"),
    }


def _type_order(row):
    """Types in the schema's order, notes of no known type last."""
    return list(schema.TYPES).index(row[0]) if row[0] else len(schema.TYPES)


def _strings(fields, key):
    value = fields.get(key)
    return [v.strip() for v in (value if isinstance(value, list) else [value]) if isinstance(v, str) and v.strip()]


def _link_targets(value):
    """The notes the wikilinks in a value or text name; a link by path names the note its path ends in."""
    texts = value if isinstance(value, list) else [value]
    targets = [m[1].strip().rsplit("/", 1)[-1] for t in texts if isinstance(t, str) for m in schema.LINK.finditer(t)]
    return [t.removesuffix(".md") for t in targets if t]


def _identifiers(kind, fields, name):
    found = set()
    if kind == schema.PERSON:
        for address in map(names.email, _strings(fields, "emails")):
            found |= {("email", address), ("domain", names.domain(address))}
        found |= {("phone", k) for k in map(names.phone_key, _strings(fields, "phones")) if k}
        for written in _strings(fields, "name") + _strings(fields, "aliases"):
            parts = names.parse_name(written)
            found |= {("token", t) for t in parts.full} | ({("key", parts.key)} if parts.key else set())
            found |= {("sound", names.koelner(parts.surname))} if parts.surname else set()
    elif kind == schema.ORGANIZATION:
        found |= {("domain", names.normalize_domain(d)) for d in _strings(fields, "domains")}
        found |= {("uid", schema.uid(u)) for u in _strings(fields, "uid_che")}
        for written in [name, *_strings(fields, "name"), *_strings(fields, "aliases")]:
            key = names.org_key(written)
            found |= {("org", key)} | {("token", t) for t in key.split()}
            found |= {("initials", names.initials(key))} if len(key.split()) > 1 else set()
    elif kind == schema.TOPIC:
        for written in [name, *_strings(fields, "name"), *_strings(fields, "aliases")]:
            found |= {("title", names.fold(written))} | {("token", t) for t in names.words(written)}
    elif kind == schema.INTERACTION:  # a thread's first email has no thread of its own, but its message id names it
        found |= {("thread", t) for t in _strings(fields, "thread") + _strings(fields, "message_id")}
        found |= {("in_reply_to", m) for m in _strings(fields, "in_reply_to")}
        found |= {("source_file", names.path_key(f)) for f in _strings(fields, "source_file") if f.strip()}
    return found


def _search_columns(note, fields, name):
    """The text full-text search finds a note by: its names, addresses, roles and body, with names also folded, so
    that "Mueller" finds Müller."""
    written = [name, *_strings(fields, "name"), *_strings(fields, "aliases"), *_strings(fields, "subject")]
    roles = [
        s for key in ("job_title", "department", "industry", "location", "question") for s in _strings(fields, key)
    ]
    emails = _strings(fields, "emails") + _strings(fields, "domains")
    body = ""
    if note:
        sections = [h for h in note.body.headings() if h != "History"]
        body = "\n".join(line for h in sections for line in note.body.lines(h))
    return " ".join(written + [names.fold(w) for w in written]), " ".join(emails), " ".join(roles), body
