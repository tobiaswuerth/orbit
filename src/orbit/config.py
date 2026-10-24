"""A vault's configuration, `99_System/orbit.toml`: the id of Me.md, the server's address, and the addresses that say
nothing about who someone is or where they work."""

import tomllib
from dataclasses import dataclass, field

from . import ids
from .errors import OrbitError

# The defaults, in the lines orbit.toml lists them on
FREE_MAIL_LINES = (
    ("gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "icloud.com", "me.com"),
    ("yahoo.com", "proton.me", "protonmail.com", "gmx.ch", "gmx.net", "bluewin.ch", "sunrise.ch"),
)
ROLE_LINES = (
    ("info", "noreply", "no-reply", "donotreply", "team", "sales", "support", "office", "hello", "contact"),
    ("admin", "newsletter", "hr", "service"),
)
FREE_MAIL_DOMAINS = tuple(d for line in FREE_MAIL_LINES for d in line)
ROLE_ADDRESSES = tuple(r for line in ROLE_LINES for r in line)
HOST, PORT = "127.0.0.1", 8775

TEMPLATE = """# orbit's configuration for this vault.

me = "{me}"  # the id of 01_People/Me.md

[server]
host = "{host}"
port = {port}
# tools = ["read", "write", "upkeep"]  # what /mcp offers, all by default; /mcp/write and /mcp/read offer less

[identity]
# Addresses at these domains say nothing about a person's employer.
free_mail_domains = [
{free_mail}
]
# Local parts of addresses, or words of them (acme-support@), that belong to a role or a mailbox, never to a person.
role_addresses = [
{roles}
]
"""


class ConfigError(OrbitError):
    pass


@dataclass(frozen=True)
class Config:
    me: str | None = None
    host: str = HOST
    port: int = PORT
    tools: tuple[str, ...] | None = None  # the tool groups or tools to serve; None for all
    free_mail_domains: frozenset[str] = field(default=frozenset(FREE_MAIL_DOMAINS))
    role_addresses: frozenset[str] = field(default=frozenset(ROLE_ADDRESSES))


def load(path):
    """The configuration in a file; the defaults for anything it leaves out, or all of them if there is no file."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))  # a byte order mark, as PowerShell writes, is fine
    except FileNotFoundError:
        return Config()
    except UnicodeDecodeError:
        raise ConfigError(f"{path} isn't UTF-8 text; save it as UTF-8") from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from None
    server, identity = _table(data, "server", path), _table(data, "identity", path)
    _no_others(data, {"me", "server", "identity"}, path)
    _no_others(server, {"host", "port", "tools"}, path, "server.")
    _no_others(identity, {"free_mail_domains", "role_addresses"}, path, "identity.")
    me = data.get("me")
    if me is not None and not ids.is_valid(me, "per"):
        raise ConfigError(f"{path}: me must be the id of Me.md, a person's id such as per_01M3V0RPR04X2CSM8CEMSVTWVA")
    port = server.get("port", PORT)
    if not isinstance(port, int) or isinstance(port, bool) or not 0 < port < 65536:
        raise ConfigError(f"{path}: server.port must be a port number")
    tools = server.get("tools")
    if tools is not None and (not isinstance(tools, list) or not all(isinstance(t, str) for t in tools)):
        raise ConfigError(f'{path}: server.tools must be a list of text, such as ["read", "write"]')
    return Config(
        me=me,
        host=_text(server.get("host", HOST), "server.host", path),
        port=port,
        tools=None if tools is None else tuple(t.strip() for t in tools if t.strip()),
        free_mail_domains=_words(identity, "free_mail_domains", FREE_MAIL_DOMAINS, path),
        role_addresses=_words(identity, "role_addresses", ROLE_ADDRESSES, path),
    )


def _table(data, name, path):
    table = data.get(name, {})
    if not isinstance(table, dict):
        raise ConfigError(f"{path}: {name} must be a table, [{name}]")
    return table


def _no_others(table, known, path, prefix=""):
    if unknown := sorted(set(table) - known):
        raise ConfigError(f"{path}: unknown setting {prefix}{unknown[0]}; known: {', '.join(sorted(known))}")


def _text(value, name, path):
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{path}: {name} must be text")
    return value.strip()


def _words(table, name, default, path):
    values = table.get(name, list(default))
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise ConfigError(f"{path}: identity.{name} must be a list of text")
    return frozenset(v.strip().lower() for v in values if v.strip())


def template(me):
    """The orbit.toml that `orbit init` writes, with the defaults and the id of Me.md."""
    return TEMPLATE.format(
        me=me,
        host=HOST,
        port=PORT,
        free_mail=_lines(FREE_MAIL_LINES),
        roles=_lines(ROLE_LINES),
    )


def _lines(groups):
    return "\n".join("  " + " ".join(f'"{word}",' for word in group) for group in groups)
