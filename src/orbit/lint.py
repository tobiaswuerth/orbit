"""lint_vault: what in the vault breaks its rules, whether orbit wrote it or its owner edited it by hand. `fix` repairs
only what is safe to repair without asking: a missing id, and addresses and domains not in lower case."""

import json
from pathlib import PurePosixPath

from . import edits, ids, index, names, schema

FOLDERS = {t.folder: t.name for t in schema.TYPES.values()}
ORDER = {"error": 0, "warning": 1}


def lint(crm, fix=False):
    crm.refresh()
    issues, fixed = [], edits.Changes()

    def issue(severity, path, rule, message):
        issues.append(
            {
                "severity": severity,
                "note": PurePosixPath(path).stem,
                "path": str(crm.vault.path(path)),
                "rule": rule,
                "message": message,
            }
        )

    for row in crm.index.db.execute("SELECT * FROM notes ORDER BY path").fetchall():
        path, fields, kind = row["path"], json.loads(row["fields"]), row["type"]
        top = PurePosixPath(path).parts[0]
        if row["error"]:
            issue("error", path, "unreadable", f"{row['error']}; fix it by hand, orbit can't read the note")
            continue
        if not fields.get("type") and top in FOLDERS:
            issue(
                "warning",
                path,
                "no type",
                f"in {top}, but not a note of orbit's: add `type: {FOLDERS[top]}`, or move it",
            )
            continue
        if not fields.get("type"):
            continue
        for field, message in schema.problems(fields):
            if field == "id" and not fields.get("id") and kind:
                if fix:
                    fixed.add(_fix(crm, path, id=ids.new(schema.TYPES[kind].prefix, crm.now())))
                else:
                    issue("error", path, "missing id", "no id; lint_vault with fix assigns one")
                continue
            issue("error", path, "schema", f"{field}: {message}")
        if not kind:
            continue
        for field in schema.unknown(kind, fields):
            issue("warning", path, "unknown field", f"{field} is kept, but isn't part of the {kind} schema")
        if top != schema.TYPES[kind].folder:
            issue("warning", path, "wrong folder", f"a {kind} belongs in {schema.TYPES[kind].folder}")
        if loud := _not_lowercase(kind, fields):
            if fix:
                fixed.add(_fix(crm, path, **loud))
            else:
                issue(
                    "warning",
                    path,
                    "not lower case",
                    f"{', '.join(loud)}: lint_vault with fix writes them in lower case",
                )
        if kind in schema.ENTITY and not fields.get("me") and _not_the_file_s(PurePosixPath(path).stem, fields):
            issue(
                "warning",
                path,
                "name not the file's",
                f"its name {fields['name']!r} isn't its file's: rename_entity to its name renames the file and the "
                "links to it; to the file's, it sets the name",
            )
        if path in crm.review_problems:
            issue("warning", path, "not applied", crm.review_problems[path])
    for clash in crm.index.clashes():
        what = index.UNIQUE[clash["kind"]]
        holder = PurePosixPath(clash["holder"]).stem
        issue(
            "error",
            clash["path"],
            "clash",
            f"its {what} {clash['value']} is also that of [[{holder}]]; one must change",
        )
    files = crm.vault.link_keys()
    broken = crm.index.db.execute(
        """SELECT path, field, target, target_key FROM links WHERE target_key NOT IN
           (SELECT value FROM claims WHERE kind = 'name') ORDER BY path, rowid"""
    )
    for row in broken:
        if row["target_key"] in files:  # a file that isn't a note
            continue
        where = f" in {row['field']}" if row["field"] else ""
        issue("warning", row["path"], "broken link", f"[[{row['target']}]]{where} leads to no note")
    issues.sort(key=lambda i: (ORDER[i["severity"]], i["path"], i["rule"]))
    counts = {s: sum(i["severity"] == s for i in issues) for s in ORDER}
    return {"issues": issues, "counts": counts, "fixed": list(fixed)}


def _not_the_file_s(stem, fields):
    """Whether a note's name isn't its file's, which links name: a file is named after the name, made safe, with a
    number or what tells it apart in brackets where another note had the name already."""
    if not isinstance(name := fields.get("name"), str) or not name.strip():
        return False  # no name is a schema problem of its own
    base, found = names.file_key(names.file_name(name)), names.file_key(stem)
    return found != base and not (found.startswith(f"{base} (") and found.endswith(")"))


def _not_lowercase(kind, fields):
    """Address and domain fields with capitals, as they should be."""
    found = {}
    for name in ("emails", "domains"):
        field = schema.TYPES[kind].field(name)
        values = edits.listed(fields.get(name))
        if field and all(isinstance(v, str) for v in values) and any(v != v.lower() for v in values):
            found[name] = [v.lower() for v in values]
    return found


def _fix(crm, path, **fields):
    note = crm.load(path)
    note.fields.update(fields)
    return crm.save(note)
