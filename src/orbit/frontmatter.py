"""Front matter: the block of `key: value` lines between two `---` lines that opens a note.

orbit reads and writes a strict, flat subset of YAML: `key: value` lines, block lists of one `- item` per line,
`key: []`, comments and blank lines. Values are strings, booleans or null; dates stay strings in ISO form. Anything
else (nested mappings, flow collections with items, multi-line strings, anchors, tags) is refused with its line, so
orbit never reads a note differently from a full YAML parser, Obsidian or a line-based reader. What `dump` writes,
any YAML parser reads back as the same values: it quotes every string that YAML would read as something else.
"""

import datetime
import re
import unicodedata

Scalar = str | bool | None
Value = Scalar | list[Scalar]

FENCE = "---"
KEY = r"[^\s:#\-?\[\]{},&*!|>'\"%@`][^:#]*?"
FIELD = re.compile(rf"(?P<key>{KEY}) *:(?: +(?P<value>.*?))? *")
ITEM = re.compile(r"(?P<indent> *)-(?: +(?P<value>.*?))? *")
NULL = {"~", "null", "Null", "NULL"}
TRUE = {"true", "True", "TRUE"}
FALSE = {"false", "False", "FALSE"}

# A string is written plain only if it starts with a letter or digit, holds nothing but these characters, and YAML
# 1.1 or 1.2 wouldn't read it as a boolean, null or number. Valid dates and times are written plain too.
PLAIN = re.compile(r"[^\W_][\w .,\-@()&']*(?<! )")
SPECIAL = {"y", "Y", "yes", "Yes", "YES", "n", "N", "no", "No", "NO", "on", "On", "ON", "off", "Off", "OFF"}
SPECIAL |= NULL | TRUE | FALSE
NUMBER = re.compile(r"\d[\d_]*(?:\.[\d_]*)?(?:[eE][-+]?\d+)?|0[xob][0-9a-fA-F_]+")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
DATETIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?[+-]\d{2}:\d{2}")
TIMESTAMP = re.compile(r"\d{4}-\d\d?-\d\d?(?:$|[Tt ])")  # what YAML takes for a date or time, valid or not

ESCAPES = {
    "0": "\x00",
    "a": "\x07",
    "b": "\x08",
    "t": "\t",
    "\t": "\t",
    "n": "\n",
    "v": "\x0b",
    "f": "\x0c",
    "r": "\r",
    "e": "\x1b",
    " ": " ",
    '"': '"',
    "/": "/",
    "\\": "\\",
    "N": "\x85",
    "_": "\xa0",
    "L": "\u2028",
    "P": "\u2029",
}
HEX_ESCAPES = {"x": 2, "u": 4, "U": 8}
WRITE_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\t": "\\t", "\r": "\\r", "\x00": "\\0"}


class FrontMatterError(ValueError):
    """Front matter orbit can't read, at a line of the file."""

    def __init__(self, line, message):
        super().__init__(f"line {line}: {message}")
        self.line = line


def split(text):
    """(front matter, body) of a note's text, with Unix line ends and without a byte-order mark. The front matter is
    None if the text doesn't open with a `---` line."""
    text = text.removeprefix("\ufeff").replace("\r\n", "\n")
    head, _, rest = text.partition("\n")
    if head.rstrip() != FENCE:
        return None, text
    lines = rest.split("\n")
    for i, line in enumerate(lines):
        if line.rstrip() == FENCE:
            return "".join(f"{x}\n" for x in lines[:i]), "\n".join(lines[i + 1 :])
    raise FrontMatterError(1, "the front matter has no closing --- line")


def read(text, raw=None):
    """(fields, body) of a note's text; fields are None if it has no front matter. See `parse` for `raw`."""
    front, body = split(text)
    return (None if front is None else parse(front, first_line=2, raw=raw)), body


def render(fields, body):
    """A note's text from its fields (None for no front matter) and body."""
    return body if fields is None else f"{FENCE}\n{dump(fields)}{FENCE}\n{body}"


def parse(text, first_line=1, raw=None):
    """The fields of front matter text, without its `---` lines; `first_line` is the file's line it starts on. A dict
    given as `raw` receives each field's lines as written, so a field can be written back exactly as it was."""
    fields, key = {}, None  # key: the field whose block list the lines are adding to, if any
    bare = set()  # keys with no value, which are null unless list items follow
    raw = {} if raw is None else raw
    for number, line in enumerate(text.split("\n"), start=first_line):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.lstrip(" ").startswith("\t"):
            raise FrontMatterError(number, "indent with spaces, not a tab")
        if item := ITEM.fullmatch(line):
            if key is None:
                raise FrontMatterError(number, "a list item must be under a key with no value")
            fields[key].append(_scalar(item["value"], number))
            bare.discard(key)
            raw[key] += f"{line}\n"
            continue
        if line.startswith(" "):
            raise FrontMatterError(number, "nested mappings and multi-line values aren't supported")
        match = FIELD.fullmatch(line)
        if not match:
            raise FrontMatterError(number, "expected `key: value`, with a space after the colon")
        name, value = match["key"], match["value"]
        if name in fields:
            raise FrontMatterError(number, f"{name} is set twice")
        raw[name] = f"{line}\n"
        if not value or value.startswith("#"):  # no value, perhaps after spaces: null, or a list below
            fields[name], key = [], name
            bare.add(name)
        else:
            fields[name], key = _value(value, number), None
    return {k: None if k in bare else v for k, v in fields.items()}


def _value(text, number):
    if text == "[]" or re.fullmatch(r"\[\] +#.*", text):
        return []
    return _scalar(text, number)


def _scalar(text, number):
    """A field's value or a list item's, as YAML reads it."""
    if not text or text[0] == "#":  # nothing, or only a comment
        return None
    if text.startswith("[["):
        raise FrontMatterError(number, 'quote a wikilink, as in "[[Acme AG]]": unquoted, YAML reads a list in a list')
    if text[0] in "[{":
        raise FrontMatterError(number, "write lists as block lists, one `- item` per line; mappings aren't supported")
    if text[0] in "|>":
        raise FrontMatterError(number, "multi-line values aren't supported")
    if text[0] == '"':
        return _double_quoted(text, number)
    if text[0] == "'":
        return _single_quoted(text, number)
    value = re.split(r"\s#", text, maxsplit=1)[0].rstrip()
    if value[0] in "&*!":
        raise FrontMatterError(number, "anchors, aliases and tags aren't supported")
    if value[0] in "%@`":
        raise FrontMatterError(number, f"{value[0]} is reserved in YAML; quote the value")
    if value[0] == "-" and value[1:2] in ("", " "):
        raise FrontMatterError(number, "a list must start on the line after its key")
    if (value[0] in "?:" and value[1:2] in ("", " ")) or ": " in value or value.endswith(":"):
        raise FrontMatterError(number, 'quote values that contain ": " or end in a colon')
    if value in NULL:
        return None
    if value in TRUE or value in FALSE:
        return value in TRUE
    return value


def _rest(text, number):
    """After a closing quote, only spaces and a comment may follow."""
    if text.strip() and not re.fullmatch(r" +#.*", text):
        raise FrontMatterError(number, "nothing but a comment may follow after the closing quote")


def _single_quoted(text, number):
    match = re.match(r"'((?:[^']|'')*)'", text)
    if not match:
        raise FrontMatterError(number, "a single-quoted value has no closing quote")
    _rest(text[match.end() :], number)
    return match[1].replace("''", "'")


def _double_quoted(text, number):
    out, i = [], 1
    while i < len(text):
        char = text[i]
        if char == '"':
            _rest(text[i + 1 :], number)
            return "".join(out)
        if char != "\\":
            out.append(char)
            i += 1
            continue
        code = text[i + 1 : i + 2]
        if code in ESCAPES:
            out.append(ESCAPES[code])
            i += 2
        elif code in HEX_ESCAPES:
            digits = text[i + 2 : i + 2 + HEX_ESCAPES[code]]
            if not re.fullmatch(r"[0-9a-fA-F]+", digits) or len(digits) != HEX_ESCAPES[code]:
                raise FrontMatterError(number, f"invalid escape \\{code}{digits}")
            out.append(chr(int(digits, 16)))
            i += 2 + len(digits)
        else:
            raise FrontMatterError(number, f"unknown escape \\{code}")
    raise FrontMatterError(number, "a double-quoted value has no closing quote")


def dump(fields):
    """Front matter text for fields, without its `---` lines, in the order given."""
    lines = []
    for key, value in fields.items():
        if not re.fullmatch(KEY, key) or key != key.strip():
            raise ValueError(f"not a key orbit can write: {key!r}")
        if value is None:
            lines.append(f"{key}:")
        elif isinstance(value, list):
            lines.append(f"{key}: []" if not value else f"{key}:")
            lines += ["  -" if v is None else f"  - {_format(v)}" for v in value]
        else:
            lines.append(f"{key}: {_format(value)}")
    return "".join(f"{line}\n" for line in lines)


def _format(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if not isinstance(value, str):
        raise TypeError(f"front matter holds strings and booleans, not {type(value).__name__}")
    if _is_date(value):
        return value
    if PLAIN.fullmatch(value) and value not in SPECIAL and not NUMBER.fullmatch(value) and not TIMESTAMP.match(value):
        return value
    escaped = "".join(WRITE_ESCAPES.get(c) or (_escape(c) if _unprintable(c) else c) for c in value)
    return f'"{escaped}"'


def _unprintable(char):
    """What YAML doesn't allow unescaped in a quoted string, or folds: control characters, line and paragraph
    separators, surrogates, the byte-order mark and noncharacters."""
    return unicodedata.category(char) in ("Cc", "Cs", "Zl", "Zp") or char in "\ufeff\ufffe\uffff"


def _escape(char):
    code = ord(char)
    return f"\\x{code:02x}" if code < 0x100 else f"\\u{code:04x}"


def _is_date(value):
    """A valid date or date and time, as YAML reads them; an invalid one, such as 2026-13-45, is just text."""
    try:
        if DATE.fullmatch(value):
            datetime.date.fromisoformat(value)
            return True
        if DATETIME.fullmatch(value):
            datetime.datetime.fromisoformat(value)
            return True
    except ValueError:
        pass
    return False
