"""What orbit tells the user while it works. It all goes to stderr, so stdout stays for the CLI's results, and an MCP
client on stdio never reads it as protocol."""

import sys


def say(*parts):
    print(*parts, file=sys.stderr, flush=True)


def count(n, noun):
    """'1 note', '2 notes', '12,345 notes'."""
    return f"{n:,} {noun}{'' if n == 1 else 's'}"


def an(noun):
    """A noun with its article: "a person", "an organization"."""
    return f"{'an' if noun[0] in 'aeiou' else 'a'} {noun}"
