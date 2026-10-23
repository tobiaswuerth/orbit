"""Note ids: a type prefix and a ULID, such as per_01M4WNN540CGMAHYXV1R90AA5V. A ULID is 48 bits of creation time in
milliseconds and 80 random bits, in Crockford's base 32, so ids sort by creation time and are never reused."""

import datetime
import os
import re

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
ULID = re.compile(rf"[0-7][{ALPHABET}]{{25}}")
ID = re.compile(rf"([a-z]{{3}})_({ULID.pattern})")


def new(prefix, when, randomness=None):
    """A new id for a note created at `when`."""
    ms = int(when.timestamp() * 1000)
    number = ms << 80 | int.from_bytes(randomness if randomness is not None else os.urandom(10))
    return f"{prefix}_{''.join(ALPHABET[number >> shift & 31] for shift in range(125, -1, -5))}"


def is_valid(value, prefix=None):
    """Whether a value is an id, and, if `prefix` is given, one with that prefix."""
    match = ID.fullmatch(value) if isinstance(value, str) else None
    return bool(match) and prefix in (None, match[1])


def timestamp(value):
    """When the note with this id was created, to the millisecond, in UTC."""
    number = 0
    for char in value.partition("_")[2][:10]:
        number = number * 32 + ALPHABET.index(char)
    return datetime.datetime.fromtimestamp(number / 1000, datetime.UTC)
