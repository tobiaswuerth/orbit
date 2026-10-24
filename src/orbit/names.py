"""Names, addresses and file names: the keys that duplicate detection compares, file names that are safe on every
system and in wikilinks, and the paths of files outside the vault."""

import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from urllib.parse import quote

TRANSLITERATE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "æ": "ae", "œ": "oe", "ø": "o", "ł": "l", "đ": "d"})
TITLES = {
    *("dr", "dres", "prof", "pd", "dipl", "ing", "lic", "iur", "phil", "med", "dent", "vet", "rer", "nat", "pol"),
    *("oec", "mag", "msc", "bsc", "ma", "ba", "mba", "phd", "eth", "fh", "herr", "frau", "mr", "mrs", "ms", "sir"),
}
LEGAL_FORMS = {
    *("ag", "aktiengesellschaft", "gmbh", "sa", "sarl", "sagl", "srl", "spa", "kg", "ohg", "eg", "ug", "se"),
    *("genossenschaft", "stiftung", "verein", "ltd", "llc", "inc", "plc", "corp", "co", "bv", "nv", "ab", "oy"),
}
RESERVED_FILE_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
UNSAFE_IN_FILE_NAMES = re.compile(r'[:/\\?*"<>|\[\]#^]')  # Windows' forbidden characters, and link syntax
MAX_FILE_NAME = 120  # characters, leaving room for the folders under Windows' 260-character path limit
MAX_FILE_BYTES = 240  # in UTF-8, as Linux and macOS count them, leaving room for " (2)" and ".md" under their 255
LABEL = r"[^\W_](?:(?:[^\W_]|-)*[^\W_])?"  # letters (umlauts too: müller.ch) and digits, hyphens inside
DOMAIN = re.compile(rf"{LABEL}(?:\.{LABEL})+")
EMAIL = re.compile(rf"[^@\s]+@{DOMAIN.pattern}")
ANGLED = re.compile(r"[^<>]*<([^<>]+)>")  # a header's display name and address: Anna Keller <anna@acme.example>
OPENED = frozenset(  # the files notes link to be opened with a click: documents, pictures, recordings; no programs
    ".pdf .doc .docx .xls .xlsx .ppt .pptx .odt .ods .odp .rtf .txt .md .csv .eml .msg .epub "
    ".png .jpg .jpeg .gif .webp .heic .tif .tiff .mp3 .m4a .wav .mp4 .mov".split()
)


def fold(text):
    """Text as names compare: Unicode NFC, case-folded, umlauts as ae, oe and ue, ß as ss, accents dropped."""
    text = unicodedata.normalize("NFC", text).casefold().translate(TRANSLITERATE)
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def file_key(name):
    """A file name as links compare it: the same name in any case or Unicode form."""
    return unicodedata.normalize("NFC", name).casefold()


def local_path(text):
    """The absolute path of a local file that a text is (C:\\…, \\\\server\\share\\…, /home/…), whichever system wrote
    it; None for anything else, such as a relative path, a URL or an id."""
    if not isinstance(text, str) or not text.strip():
        return None
    windows = PureWindowsPath(text.strip())
    if windows.drive and windows.root:
        return windows
    return PurePosixPath(text.strip()) if text.strip().startswith("/") else None


def file_link(text):
    """The file:// URL a note links a local file by, which Obsidian opens with the file's program, such as
    file:///C:/Offers/Offer%20v2.pdf: for a document, picture or recording on this computer. None for anything else:
    a click must neither run a program nor send the owner's credentials to the computer a share is on."""
    path = local_path(text)
    if path is None or path.suffix.lower() not in OPENED or path.drive.startswith("\\\\"):
        return None
    if isinstance(path, PureWindowsPath):  # C:/Offers/… as file:///C:/Offers/…
        return f"file:///{path.drive}{quote(path.as_posix()[len(path.drive) :])}"
    return f"file://{quote(path.as_posix())}"


def path_key(text):
    """A file path as paths compare: forward slashes, without repeats, in any case or Unicode form."""
    return file_key(re.sub(r"/+", "/", text.strip().replace("\\", "/")))


@dataclass(frozen=True)
class Name:
    full: tuple[str, ...]  # folded words of two letters or more, in the order written
    initials: tuple[str, ...]  # single letters, such as the H of "H. Müller"
    surname: str | None  # the word before a comma, as directories write "Müller, Hans", or else the last word

    @property
    def key(self):
        """The name with its words in any order: "Hans Müller", "Müller, Hans" and "Mueller Hans" share it."""
        return " ".join(sorted(self.full))


def parse_name(name):
    """A person's name in parts, without titles such as Dr., Prof. or dipl. Ing."""
    full, initials, surname = [], [], None
    family, _, given = name.partition(",") if "," in name else ("", "", name)
    for part, words in (("family", family), ("given", given)):
        for word in words.split():
            letters = re.sub(r"[^\w]|_|\d", "", fold(word))
            if not letters or letters in TITLES:
                continue
            if len(letters) == 1:
                initials.append(letters)
                continue
            full.append(letters)
            if part == "family" or not family:
                surname = surname if part == "family" and surname else letters
    return Name(tuple(full), tuple(initials), surname)


def koelner(word):
    """The Kölner Phonetik code of a word: German names that sound alike, such as Müller and Möller, share it."""
    letters = re.sub("[^A-Z]", "", fold(word).upper())
    digits = []
    for i, c in enumerate(letters):
        before, after = letters[i - 1 : i], letters[i + 1 : i + 2]
        if c in "AEIJOUY":
            digits.append("0")
        elif c in "BP":
            digits.append("3" if c == "P" and after == "H" else "1")
        elif c in "DT":
            digits.append("8" if after and after in "CSZ" else "2")
        elif c in "FVW":
            digits.append("3")
        elif c in "GKQ":
            digits.append("4")
        elif c == "C":
            hard = "AHKLOQRUX" if i == 0 else "AHKOQUX"
            digits.append("4" if after and after in hard and not (before and before in "SZ") else "8")
        elif c == "X":
            digits.append("8" if before and before in "CKQ" else "48")
        elif c == "L":
            digits.append("5")
        elif c in "MN":
            digits.append("6")
        elif c == "R":
            digits.append("7")
        elif c in "SZ":
            digits.append("8")
    code = re.sub(r"(\d)\1+", r"\1", "".join(digits))
    return code[:1] + code[1:].replace("0", "")


def words(text):
    """The folded words of a text."""
    return re.findall(r"[^\W_]+", fold(text))


def org_key(name):
    """An organization's name without its legal form: "Acme AG" and "ACME Aktiengesellschaft" share "acme"."""
    found = words(name)
    return " ".join([w for w in found if w not in LEGAL_FORMS] or found)


def initials(key):
    """The first letters of the words of an organization's key: azo for "ausbildungszentrum zuercher oberland"."""
    return "".join(word[0] for word in key.split())


def email(address):
    """An email address as orbit stores it: trimmed and lowercased."""
    return address.strip().lower()


def is_email(address):
    return bool(EMAIL.fullmatch(address))


def address(text):
    """The email address a text is, bare or as an email's header writes it, "Anna Keller <anna@acme.example>", as
    orbit stores it; None if it is none."""
    angled = ANGLED.fullmatch(text.strip()) if isinstance(text, str) else None
    found = email(angled[1] if angled else text) if isinstance(text, str) else ""
    return found if is_email(found) else None


def domain(address):
    return address.rpartition("@")[2]


def email_tokens(address):
    """The words of an address's local part, which often spell the person's name: hansi.mueller → hansi, mueller."""
    local = address.partition("@")[0].partition("+")[0]
    return re.findall(r"[a-z]+", fold(local))


def is_role_address(address, roles):
    """Whether an address belongs to a role or a mailbox (info@, noreply@), never to a person. Its whole local part
    decides: a role word in a person's address (anna.office@) doesn't make it a mailbox."""
    return email(address).partition("@")[0].partition("+")[0] in roles


def normalize_domain(text):
    """A domain as orbit stores it, also from a web address: lowercased, without scheme, login, port, path, www. or
    final dot."""
    host = re.sub(r"^[a-z][a-z0-9+.-]*://", "", text.strip().lower()).split("/")[0]
    return host.rpartition("@")[2].split(":")[0].removeprefix("www.").rstrip(".")


def is_domain(text):
    return bool(DOMAIN.fullmatch(text))


def parent_domains(domain):
    """The domains a domain is under, nearest first, down to two labels: students.school.example → school.example."""
    labels = domain.split(".")
    return [".".join(labels[i:]) for i in range(1, len(labels) - 1)]


def phone_key(number):
    """The last nine digits of a phone number, which match whichever way it was written (+41 52…, 052…, 0041 52…);
    None for a number too short to tell."""
    digits = re.sub(r"\D", "", number)
    return digits[-9:] if len(digits) >= 7 else None


def file_name(name):
    """A name as a file name: safe on Windows, macOS and Linux, and in a [[wikilink]]; a long one cut at a word."""
    name = UNSAFE_IN_FILE_NAMES.sub("", name)
    name = re.sub(r"\s+", " ", "".join(" " if unicodedata.category(c)[0] == "C" else c for c in name))
    name = name.strip(" .")
    if len(name) > MAX_FILE_NAME or len(name.encode()) > MAX_FILE_BYTES:
        limit = MAX_FILE_NAME
        while len(name[:limit].encode()) > MAX_FILE_BYTES:
            limit -= 1
        cut = name[: limit + 1]
        name = cut[: cut.rindex(" ")] if " " in cut else name[:limit]
        name = name.strip(" .")
    base, dot, rest = name.partition(".")  # Windows reserves CON and the like with any extension, too
    if base.rstrip().lower() in RESERVED_FILE_NAMES:
        name = f"{base}_{dot}{rest}"
    return name or "Untitled"


class Nicknames:
    """First names that can stand for one another (Hans, Hansi, Hansruedi), from nicknames.txt: one group per line,
    names separated by "=", comments after "#"."""

    def __init__(self, groups):
        self._groups = {}
        for group in groups:
            folded = frozenset(fold(name) for name in group)
            for name in folded:
                self._groups[name] = self._groups.get(name, frozenset()) | folded

    @classmethod
    def parse(cls, text):
        lines = (line.partition("#")[0] for line in text.splitlines())
        groups = [[n.strip() for n in line.split("=") if n.strip()] for line in lines]
        return cls(group for group in groups if len(group) > 1)

    def variants(self, name):
        """A folded first name with all the names that can stand for it."""
        return self._groups.get(name, frozenset()) | {name}

    def same(self, a, b):
        return fold(b) in self.variants(fold(a))
