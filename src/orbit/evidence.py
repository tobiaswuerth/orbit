"""Evidence checked against its source: a quote must be in the file its interaction was logged from, as written,
where orbit can read that file. Case, spaces, quotation marks, Markdown emphasis and the `>` an email quotes earlier
ones with aside; parts of a quote that aren't together in the source are joined with … (or ..., [...], " ; ", " / ")."""

import re
import unicodedata
from pathlib import Path

from . import edits, names, schema

TEXT = (".md", ".markdown", ".txt")  # the files orbit reads to check a quote
JOINS = re.compile(r"\s*(?:\[\.\.\.\]|\[…\]|\.\.\.|…|\s;\s|\s/\s)\s*")
MARKS = re.compile(r"[\"'“”„‘’‹›«»*_`\\]")
QUOTED = re.compile(r"^[ \t]*(?:>[ \t]*)+", re.MULTILINE)  # the markers of an email's quoted lines, nested too
SHOWN = 8  # words of a quote an error shows, from where it parts from the source


def fold(text):
    """Text as quotes compare: Unicode NFKC, case-folded, without quotation marks, emphasis and the markers of
    quoted lines, spaces collapsed."""
    return " ".join(MARKS.sub("", QUOTED.sub("", unicodedata.normalize("NFKC", text)).casefold()).split())


def unquoted(crm, link, quote):
    """The part of `quote` from where it parts from the source `link` names, or None: if all of it is in the source,
    or orbit can't tell, as for a source that isn't an interaction logged from a text file orbit can read, or one
    with a document orbit can't read (a PDF, say), which the quote may come from."""
    target = schema.link_target(link) if isinstance(link, str) else None
    source = crm.find(target) if target else None
    if source is None or source.type != schema.INTERACTION:
        return None
    files = [source.fields.get("source_file")] + [
        match[2].strip("<>")
        for item in edits.listed(source.fields.get("documents"))
        if isinstance(item, str) and (match := schema.DOCUMENT.fullmatch(item))
    ]
    texts = []
    for i, written in enumerate(files):
        path = names.local_path(str(written or ""))
        if path is None or not Path(path).is_file():
            if i == 0:
                return None  # the source itself gone, or not a file
            continue
        if Path(path).suffix.lower() not in TEXT:
            return None
        texts.append(fold(Path(path).read_text(encoding="utf-8", errors="replace")))
    found = " ".join(texts)
    for part in JOINS.split(quote):
        words = fold(part).split()
        if words and " ".join(words) not in found:
            kept = next(n for n in range(len(words) - 1, -1, -1) if " ".join(words[:n]) in found)
            return " ".join(part.split()[kept : kept + SHOWN])
    return None
