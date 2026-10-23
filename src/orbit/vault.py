"""A vault: its folders, its notes as files, and `orbit init`. Notes are written atomically (a temporary file, then a
rename), so Obsidian, sync tools and other readers never see half a note."""

import copy
import os
import time
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path, PurePosixPath

from . import bases, config, frontmatter, ids, names, schema
from .errors import OrbitError
from .sections import Body, build

SYSTEM = "99_System"
CONFIG = f"{SYSTEM}/orbit.toml"
NICKNAMES = f"{SYSTEM}/nicknames.txt"
AGENTS = f"{SYSTEM}/AGENTS.md"
ME = "01_People/Me.md"
NOT_NOTES = {SYSTEM, bases.FOLDER}  # top-level folders that hold no notes
TRASH = ".trash"  # where Obsidian puts deleted notes, so they can be restored
REPLACE_ATTEMPTS = 6  # Windows refuses to replace a file another program has open; it usually closes it soon

NICKNAMES_TEMPLATE = """# First names that can stand for one another, one group per line. Used for candidates only.
Hans = Hansi = Hansruedi
Rudolf = Ruedi
Jakob = Köbi
Christian = Chrigu = Chrigi
Franziska = Fränzi = Franzi
Ulrich = Ueli
Andreas = Res = Andi
Daniel = Dani = Dänu
Thomas = Thomi = Tom
"""
AGENTS_TEMPLATE = """# For agents

This vault is a personal CRM, managed by orbit.

- Read any note freely.
- Write only through orbit's MCP tools, never by editing files. orbit checks for duplicates, keeps the schema and \
records where each fact came from.
- Before creating a person or an organization, call `resolve_entity` and decide whether one of its candidates is the \
same.
- Write only what a source states, and name the source.
- `## Notes` sections belong to {owner}. Leave them alone.
"""


@dataclass
class Note:
    """A note: front matter (None if it has none) and body. Rendering a note read from a file gives back its text
    unchanged as long as its fields are; once they change, the fields orbit didn't change keep their lines as written,
    and the schema's order."""

    path: str  # in the vault, with forward slashes: "01_People/Hans Müller.md"
    fields: dict | None
    body: Body
    _front: str | None = None  # the front matter as read
    _read: dict = field(default_factory=dict)  # the fields as read
    _raw: dict = field(default_factory=dict)  # their lines as written

    @classmethod
    def parse(cls, path, text):
        """Raises frontmatter.FrontMatterError for front matter orbit can't read."""
        raw = {}
        front, body = frontmatter.split(text)
        fields = None if front is None else frontmatter.parse(front, first_line=2, raw=raw)
        return cls(path, fields, Body.parse(body), front, copy.deepcopy(fields) or {}, raw)

    @property
    def name(self):
        """The file name without .md: the note's name in links."""
        return PurePosixPath(self.path).stem

    @property
    def type(self):
        kind = (self.fields or {}).get("type")
        return kind if kind in schema.TYPES else None

    def text(self):
        if self.fields is None:
            return self.body.text()
        if self._front is not None and self.fields == self._read:
            return f"{frontmatter.FENCE}\n{self._front}{frontmatter.FENCE}\n{self.body.text()}"
        fields = schema.order(self.type, self.fields) if self.type else self.fields
        front = "".join(
            self._raw[k] if k in self._raw and v == self._read.get(k) else frontmatter.dump({k: v})
            for k, v in fields.items()
        )
        return f"{frontmatter.FENCE}\n{front}{frontmatter.FENCE}\n{self.body.text()}"


def is_note_path(path):
    """Whether a path in a vault is one orbit reads as a note: Markdown, outside the system folders and hidden ones."""
    return path.endswith(".md") and PurePosixPath(path).parts[0] not in NOT_NOTES and not is_hidden(path)


def is_hidden(path):
    """Whether a path in a vault is in a hidden folder or names a hidden file, such as Obsidian's .obsidian."""
    return any(part.startswith(".") for part in PurePosixPath(path).parts)


class Vault:
    def __init__(self, root):
        self.root = Path(root).resolve()

    @cached_property
    def config(self):
        return config.load(self.path(CONFIG))

    @cached_property
    def nicknames(self):
        try:
            text = self.path(NICKNAMES).read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            return names.Nicknames([])
        except UnicodeDecodeError:
            raise OrbitError(f"{self.path(NICKNAMES)} isn't UTF-8 text; save it as UTF-8") from None
        return names.Nicknames.parse(text)

    def reload(self):
        """Read orbit.toml and nicknames.txt again when next asked for."""
        self.__dict__.pop("config", None)
        self.__dict__.pop("nicknames", None)

    def path(self, rel):
        return self.root / rel

    def rel(self, path):
        """A file's path in the vault, with forward slashes; None if it is outside the vault, or the vault itself."""
        try:
            found = Path(path).resolve().relative_to(self.root).as_posix()
        except ValueError:
            return None
        return None if found == "." else found

    def files(self):
        """{path: (mtime_ns, size)} of every note file, in path order."""
        found = {}
        for folder, dirs, files in os.walk(self.root):
            here = Path(folder).relative_to(self.root).as_posix()
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not (here == "." and d in NOT_NOTES))
            for name in files:
                rel = name if here == "." else f"{here}/{name}"
                if is_note_path(rel):
                    try:
                        stat = os.stat(os.path.join(folder, name))
                    except FileNotFoundError:  # gone since its folder was listed, or a link that leads nowhere
                        continue
                    found[rel] = (stat.st_mtime_ns, stat.st_size)
        return dict(sorted(found.items()))

    def link_keys(self):
        """Every file in the vault outside its hidden folders, as links name and compare them: Obsidian links to any
        file, a Bases view, an attachment or a system file as well as a note."""
        found = set()
        for _, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            found |= {names.file_key(f.removesuffix(".md")) for f in files}
        return found

    def stat(self, rel):
        """(mtime_ns, size) of a file, or None if it is gone."""
        try:
            stat = self.path(rel).stat()
        except FileNotFoundError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def read(self, rel):
        return self.path(rel).read_bytes()

    def note(self, rel):
        return Note.parse(rel, self.read(rel).decode("utf-8"))

    def write(self, rel, text):
        """Write a file atomically, with Unix line ends, creating its folder."""
        path = self.path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")  # hidden, so no reader takes it for a note
        try:
            with open(temporary, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            _replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def rename(self, old, new):
        """Rename a file in the vault, refusing to replace another; a change of case alone is a rename."""
        source, target = self.path(old), self.path(new)
        if target.exists() and not os.path.samefile(source, target):
            raise FileExistsError(f"{new} exists already")
        target.parent.mkdir(parents=True, exist_ok=True)
        _replace(source, target)

    def trash(self, rel):
        """Move a note into .trash, as Obsidian deletes notes: under its own name, or `name (2)` if that is taken.
        The path it went to."""
        name = PurePosixPath(rel)
        stems = [name.stem, *(f"{name.stem} ({n})" for n in range(2, 10_000))]
        target = next(f"{TRASH}/{s}{name.suffix}" for s in stems if not self.path(f"{TRASH}/{s}{name.suffix}").exists())
        self.rename(rel, target)
        return target


def _replace(source, target):
    """os.replace, waiting a little for a file another program has open, which Windows refuses to move."""
    for attempt in range(REPLACE_ATTEMPTS - 1):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            time.sleep(0.02 * 2**attempt)
    os.replace(source, target)  # the last attempt, whose error is the caller's


def init(root, owner=None, emails=(), now=None):
    """Create a vault's folders, Me.md, orbit.toml, nicknames.txt, AGENTS.md and the Bases views, leaving any that
    exist as they are. Returns the paths it created. `now` is an aware datetime: when Me.md is created."""
    vault = Vault(root)
    me = _me(vault) if vault.path(ME).exists() and not vault.path(CONFIG).exists() else None  # for orbit.toml
    created = []
    for folder in [*(t.folder for t in schema.TYPES.values()), bases.FOLDER, SYSTEM]:
        if not vault.path(folder).is_dir():
            vault.path(folder).mkdir(parents=True)
            created.append(f"{folder}/")
    if not vault.path(ME).exists():
        me = ids.new("per", now)
        today = now.date().isoformat()
        fields = {"type": "person", "id": me, "name": owner or "Me", "me": True}
        fields |= {"emails": [schema.clean("person", "emails", list(emails))][0]} if emails else {}
        fields |= {"created": today, "updated": today}
        vault.write(ME, frontmatter.render(fields, build([("Notes", [])])))
        created.append(ME)
    for rel, text in [
        (CONFIG, config.template(me)),
        (NICKNAMES, NICKNAMES_TEMPLATE),
        (AGENTS, AGENTS_TEMPLATE.format(owner=owner or "the vault's owner")),
        *((f"{bases.FOLDER}/{name}", text) for name, text in bases.templates().items()),
    ]:
        if not vault.path(rel).exists():
            vault.write(rel, text)
            created.append(rel)
    return created


def my_addresses(root):
    """The addresses Me.md lists: none if it lists none, or can't be read."""
    try:
        emails = (Vault(root).note(ME).fields or {}).get("emails")
    except (OSError, frontmatter.FrontMatterError, UnicodeDecodeError):
        return []
    return [e for e in (emails if isinstance(emails, list) else [emails]) if isinstance(e, str) and e.strip()]


def _me(vault):
    """The id of the Me.md a vault has already, for its orbit.toml."""
    try:
        me = (vault.note(ME).fields or {}).get("id")
    except (frontmatter.FrontMatterError, UnicodeDecodeError):
        me = None
    if not ids.is_valid(me, "per"):
        raise OrbitError(
            f"{ME} has no person's id for orbit.toml to name; fix its front matter, or move it out of the vault and "
            "run init again"
        )
    return me
