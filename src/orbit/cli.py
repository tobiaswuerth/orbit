"""The `orbit` command. Results go to stdout; everything else orbit says goes to stderr."""

import argparse
import datetime
import json
from pathlib import Path

from . import __version__, console, index, lint, server, settings, vault
from .crm import Crm
from .errors import OrbitError, VaultInUse

PLURALS = {"person": "people"}


def parser():
    p = argparse.ArgumentParser(prog="orbit", description="A personal CRM as a vault of Markdown notes.")
    p.add_argument("--version", action="version", version=f"orbit {__version__}")
    commands = p.add_subparsers(dest="command", metavar="command")

    def command(name, help, **kwargs):
        c = commands.add_parser(name, help=help, description=help[0].upper() + help[1:] + ".", **kwargs)
        c.add_argument("vault", nargs="?", default=".", type=_folder, help="the vault's folder (default: this one)")
        return c

    init = command("init", "create a vault, or add what one lacks: its folders, Me.md, 99_System and the Bases views")
    init.add_argument("--name", help="your name, for Me.md")
    init.add_argument("--email", action="append", default=[], help="one of your addresses; repeat for several")
    serve = command("serve", "serve the vault to agents over MCP, and watch it for edits made elsewhere")
    serve.add_argument(
        "--stdio", action="store_true", help="speak MCP over stdin and stdout, to a client that starts it"
    )
    serve.add_argument("--host", help="the address to listen on (default: orbit.toml's, 127.0.0.1)")
    serve.add_argument("--port", type=_port, help="the port to listen on (default: orbit.toml's, 8775)")
    serve.add_argument(
        "--tools",
        type=lambda text: [n.strip() for n in text.split(",") if n.strip()],
        help="the tool groups (read, write, upkeep) or tools to serve, comma-separated (default: orbit.toml's, all)",
    )
    command("reindex", "build the vault's index again from its notes")
    check = command("lint", "check the vault against its rules")
    check.add_argument("--fix", action="store_true", help="repair what is safe: missing ids, addresses in capitals")
    check.add_argument("--json", action="store_true", help="as JSON")
    status = command("status", "notes per type, pending reviews and the state of the index")
    status.add_argument("--json", action="store_true", help="as JSON")
    return p


def _folder(text):
    """A folder given on the command line; a leading ~ is the home folder, also where PowerShell and cmd pass it on."""
    return Path(text).expanduser()


def _port(text):
    port = int(text) if text.strip().isdigit() else 0
    if not 0 < port < 65536:
        raise argparse.ArgumentTypeError("a port number, 1 to 65535")
    return port


def main(argv=None):
    p = parser()
    try:
        args = p.parse_args(argv)
    except SystemExit as e:
        return e.code
    if not args.command:
        p.print_help()
        return 0
    try:
        return COMMANDS[args.command](args)
    except (OrbitError, OSError) as e:  # OSError: the file system's, such as a folder orbit may not write to
        console.say(f"orbit: {e}")
        return 1
    except KeyboardInterrupt:  # Ctrl+C, the way to stop `orbit serve`
        return 130


def init(args):
    created = vault.init(args.vault, args.name, args.email, datetime.datetime.now().astimezone())
    for path in created:
        print(f"created {path}")
    if vault.ME not in created and (args.name or args.email):
        console.say(f"{vault.ME} exists already, so --name and --email changed nothing: edit it instead")
    elif not created:
        console.say(f"{Path(args.vault).resolve()} is a vault already; nothing to add")
    if not vault.my_addresses(args.vault):
        console.say(
            f"{vault.ME} has no email address, so orbit can't tell mail from and to you: add yours to its emails"
        )
    return 0


def serve(args):
    server.serve(args.vault, args.host, args.port, args.stdio, args.tools)
    return 0


def reindex(args):
    with Crm(args.vault) as crm:
        crm.index.rebuild()
        print(f"indexed {_notes(crm.index.counts())}")
    return 0


def check(args):
    """Exits with 1 if errors remain, so scripts can stop on them."""
    with Crm(args.vault) as crm:
        result = lint.lint(crm, args.fix)
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            for fixed in result["fixed"]:
                print(f"fixed: {crm.vault.rel(fixed['path'])}")
            for issue in result["issues"]:
                print(f"{issue['severity']}: {crm.vault.rel(issue['path'])}: {issue['message']}")
            counts = result["counts"]
            console.say(f"{console.count(counts['error'], 'error')}, {console.count(counts['warning'], 'warning')}")
    return 1 if result["counts"]["error"] else 0


def status(args):
    root = Path(args.vault).resolve()
    path = index.location(root, settings.current().home)
    try:
        with Crm(root) as crm:
            crm.refresh()
            state, serving = crm.index.summary(), False
    except VaultInUse:
        db = index.read_only(path)
        if db is None:
            raise
        state, serving = index.summary(db), True
        db.close()
    if args.json:
        print(json.dumps({"vault": str(root), "index": str(path), "serving": serving, **state}, indent=2))
        return 0
    print(f"vault: {root}")
    print(f"index: {path}" + (" (kept up to date by a running orbit)" if serving else ""))
    print(f"notes: {_notes(state['notes'])}")
    print(f"pending reviews: {state['pending_reviews']:,}")
    print(f"clashes: {state['clashes']:,}, unreadable notes: {state['unreadable']:,}")
    return 0


def _notes(counts):
    """'11 notes: 4 people, 1 organization, ...'."""
    total = sum(counts.values())
    parts = [
        f"{n:,} {PLURALS.get(t, f'{t}s') if n != 1 else t}" if t else f"{n:,} other" for t, n in counts.items() if n
    ]
    return console.count(total, "note") + (f": {', '.join(parts)}" if parts else "")


COMMANDS = {"init": init, "serve": serve, "reindex": reindex, "lint": check, "status": status}
