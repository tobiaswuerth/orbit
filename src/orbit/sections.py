"""Note bodies as `## ` sections. orbit appends to the sections it manages and replaces those the caller gives,
and leaves every other byte as it was: parsing a body and rendering it gives back the same text."""

import re

HEADING = re.compile(r"## +(.+?)[ #]*")
FENCE = re.compile(r" {0,3}(```|~~~)")
BLOCK = re.compile(r"( {0,3})(?:#{1,6}(?=\s|$)|```|~~~)")  # what opens a heading or a code fence


class Body:
    """A body's lines, with their line ends, in chunks: what comes before the first heading, then one chunk per
    section, opening with its heading line."""

    def __init__(self, chunks):
        self.chunks = chunks

    @classmethod
    def parse(cls, text):
        chunks, fence = [[]], None
        for line in text.splitlines(keepends=True):
            if fence is None and HEADING.fullmatch(line.rstrip("\r\n")):
                chunks.append([])
            if mark := FENCE.match(line):
                fence = None if fence == mark[1] else fence or mark[1]
            chunks[-1].append(line)
        return cls(chunks)

    def text(self):
        return "".join("".join(chunk) for chunk in self.chunks)

    def headings(self):
        return [_heading(chunk) for chunk in self.chunks[1:]]

    def lines(self, heading):
        """A section's lines, without line ends or the blank lines it ends with; None if there is no such section."""
        chunk = self._find(heading)
        return None if chunk is None else [line.rstrip("\r\n") for line in chunk[1 : _end(chunk)]]

    def append(self, heading, lines, order):
        """Add lines at the end of a section, creating it where `order`, the type's sections, puts it."""
        chunk = self._find(heading) or self._create(heading, order)
        at = _end(chunk)
        chunk[at - 1] = _terminated(chunk[at - 1])
        chunk[at:at] = [f"{line}\n" for line in lines]

    def rewrite(self, change):
        """Pass every line, line end and all, through `change`."""
        self.chunks = [[change(line) for line in chunk] for chunk in self.chunks]

    def replace(self, heading, lines, order):
        """Set a section's lines, keeping the blank lines it ends with."""
        chunk = self._find(heading) or self._create(heading, order)
        chunk[1 : _end(chunk)] = [f"{line}\n" for line in lines]

    def _find(self, heading):
        return next((chunk for chunk in self.chunks[1:] if _heading(chunk) == heading), None)

    def _create(self, heading, order):
        """A new, empty section, before the first one that `order` puts after it, or else last; separated from the
        sections around it by a blank line."""
        later = order[order.index(heading) + 1 :] if heading in order else ()
        at = next((i for i, chunk in enumerate(self.chunks) if i and _heading(chunk) in later), len(self.chunks))
        chunk = [f"## {heading}\n"]
        if at < len(self.chunks):
            chunk.append("\n")
        before = self.chunks[at - 1]
        if before:
            before[-1] = _terminated(before[-1])
            if before[-1].strip():
                before.append("\n")
        self.chunks.insert(at, chunk)
        return chunk


def build(sections):
    """The body of a new note: (heading, lines) pairs, one blank line between sections."""
    return "\n".join("".join(f"{line}\n" for line in [f"## {h}", *lines]) for h, lines in sections)


def text_lines(text):
    """Lines of text a caller gives for a section, as they are, except that a line that would open a heading or a code
    fence is escaped with a backslash, as Markdown allows: it shows the same, but can't break the note's sections."""
    return [f"{m[1]}\\{line[len(m[1]) :]}" if (m := BLOCK.match(line)) else line for line in text.splitlines()]


def _heading(chunk):
    return HEADING.fullmatch(chunk[0].rstrip("\r\n"))[1]


def _end(chunk):
    """Where a section's trailing blank lines begin."""
    at = len(chunk)
    while at > 1 and not chunk[at - 1].strip():
        at -= 1
    return at


def _terminated(line):
    return line if line.endswith("\n") else f"{line}\n"
