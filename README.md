# orbit: a personal CRM as Markdown notes, kept by an MCP server

[![CI](https://github.com/tobiaswuerth/orbit/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/tobiaswuerth/orbit/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/orbit-crm)](https://pypi.org/project/orbit-crm/)
[![Python](https://img.shields.io/pypi/pyversions/orbit-crm?logo=python&logoColor=white)](https://pypi.org/project/orbit-crm/)
[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen)](https://github.com/tobiaswuerth/orbit/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/tobiaswuerth/orbit)](https://github.com/tobiaswuerth/orbit/blob/main/LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)

orbit keeps a personal CRM as an Obsidian vault of Markdown notes: the people in your network, their organizations,
your interactions with them, the tasks that come out of those, and the topics that keep coming back. You read and
edit the notes in Obsidian or any editor; AI agents read and change them through orbit's MCP tools, which know what a
person, an organization or an interaction is, and keep the vault trustworthy:

- **One note per person, no duplicates.** Agents resolve before they write: `resolve_entity` finds candidates by email
  address, name in any order or spelling (Müller, Mueller, "Müller, Hans", H. Müller), nickname, sound-alike surname
  and company domain, each with its evidence. The agent decides, and orbit checks it when the note is created: a
  "new" person whose address is known, or a person, organization or topic too like one there (the same name, its
  initials, most of its words) is refused with the notes it is like, so that two agents at once create one note,
  not two. Unsure cases become questions you answer in Obsidian, whose answers act: a duplicate decided `same` is
  merged, an address confirmed is added, a job change confirmed is made.
- **Evidence as written.** An observation's quote must be in the email it comes from, word for word.
- **No invented fields.** Every write is checked against the schema of its note type. Fields you add by hand are kept.
- **Every fact with its source.** Observations carry the words that state them and the interaction they come from;
  field changes are dated, so an older email can't overwrite a newer fact.
- **The notes are the truth.** A SQLite index beside the vault makes lookups fast and guarantees uniqueness, but it is
  derived from the notes alone: delete it, and orbit builds it again. Edits made in Obsidian are indexed within a
  second, and on 50,000 interactions tools still answer in milliseconds ([benchmarks](docs/benchmarks.md)).
- **Upkeep that keeps links intact.** Merging two notes, renaming one, or creating the notes that links point to
  rewrites every link that needs it, in front matter and text, as Obsidian does.

Everything runs locally: no LLM inside, no network access, no cloud.

## Install

Requires Python 3.11 or newer. With [uv](https://docs.astral.sh/uv/):

```bash
uv tool install orbit-crm   # installs the `orbit` command
```

Or run it without installing, `uvx orbit-crm serve ~/crm`, or install it with pip into a virtual environment:
`pip install orbit-crm`. The package is called `orbit-crm` and installs the command twice, as `orbit` and as
`orbit-crm`.

Create a vault, with your own note, `Me.md`, and your addresses, so that agents never take you for a contact:

```bash
orbit init ~/crm --name "Tobias" --email tobias@example.com
```

Open the folder as a vault in Obsidian. `orbit init` also writes three [Bases](https://obsidian.md/help/bases) views
to `95_Bases/`, tables you can sort, filter and edit in place: **People** (everyone, by organization, not contacted
for a year, to confirm), **Follow-ups** (open tasks, tasks others owe you, people to get back to within two weeks)
and **Review** (questions waiting for your answer). Run `orbit init` on an existing vault to add what it lacks; it
never overwrites a file, so it leaves an existing `Me.md` as it is: add more addresses to its `emails` yourself. As
long as `Me.md` has none, `orbit init` says so.

## Setting up the MCP server

1. **Start the server**, and leave it running:

   ```bash
   orbit serve ~/crm       # prints: orbit MCP server on http://127.0.0.1:8775/mcp
   ```

   It brings the index up to date, then watches the vault, so edits made in Obsidian count at once; hidden folders,
   such as Obsidian's `.obsidian`, are left out. To have it always there, start it at login with your system's
   scheduler (Task Scheduler, launchd, systemd).

2. **Register it with your agent**, once. With Claude Code, for all your projects:

   ```bash
   claude mcp add --scope user --transport http orbit http://127.0.0.1:8775/mcp
   ```

   Keep `--scope user`: without it, the server is registered for the current folder only, and sessions started
   anywhere else don't see it. Other MCP clients connect the same way, to the streamable HTTP endpoint
   `http://127.0.0.1:8775/mcp`; a client configured with JSON typically takes
   `{"mcpServers": {"orbit": {"type": "http", "url": "http://127.0.0.1:8775/mcp"}}}`.

3. **Start a new agent session**: running sessions don't pick up new servers. `claude mcp list` should show orbit as
   connected, and an agent asked who is in your CRM answers from it. Connected agents receive orbit's rules in the
   server's instructions: resolve before writing, write only what a source states, and name the source.

One server serves any number of agents, and gives each the tools its URL asks for: `/mcp` all of them,
`/mcp/write` all but upkeep (merges, renames, creating missing references, lint), and `/mcp/read` only reading. An
agent that should log mail but never merge connects to `http://127.0.0.1:8775/mcp/write`, whatever its client can
hide. orbit.toml's `server.tools`, or `orbit serve --tools read,write`, narrows `/mcp` itself, and the others with it.
Every endpoint also offers the resource `orbit://vault`, for programs that need to know what a server serves: the
vault's folder, orbit's version and the number of notes of each type, as JSON.

Alternatively, a client can start orbit itself and speak to it over stdio:

```bash
claude mcp add --scope user orbit -- orbit serve --stdio ~/crm
```

But only one orbit process may open a vault at a time, so with stdio a second session's orbit is refused while the
first runs: use HTTP when several sessions work at once. Web connectors (in claude.ai, for example) can't use orbit:
they reach servers from the provider's cloud, which can't reach one on your computer.

## Updating

```bash
uv tool upgrade orbit-crm   # with pip: pip install -U orbit-crm
orbit --version
```

Then **restart `orbit serve`** (Ctrl+C, and start it again; a stdio server starts anew with each session), and
**start new agent sessions**: a client reads the tools and their parameters when a session starts, and keeps that
list, so a running session misses new tools and parameters. When a new version changes the index's layout, orbit
rebuilds the index from the notes on its first start, by itself. The [changelog](CHANGELOG.md) lists what changed.

## The vault

```
crm/
├── 01_People/          Hans Müller.md, and Me.md for you
├── 02_Organizations/   Acme AG.md
├── 03_Interactions/
│   └── 2026/2026-10/   2026-10-14 Email – AW Offerte Wartungsvertrag 2027.md
├── 04_Tasks/
├── 05_Topics/          projects, deals in progress, recurring themes
├── 90_Review/          questions for you: possible duplicates, job changes
├── 95_Bases/           Obsidian Bases views: People, Follow-ups, Review
└── 99_System/          orbit.toml, nicknames.txt, AGENTS.md
```

A person, as orbit writes them:

```markdown
---
type: person
id: per_01M4WNN540CGMAHYXV1R90AA5V
name: Hans Müller
emails:
  - hans.mueller@acme-ag.example
org: "[[Acme AG]]"
job_title: Leiter Einkauf
colleague_of:
  - "[[Anna Keller]]"
last_contact: 2026-10-14
review_status: confirmed
created: 2026-10-14
updated: 2026-10-14
---
## Notes

## Observations
- 2026-10-14 · Decides on the budget for the 2027 maintenance contract · «Das Budget für 2027 ist freigegeben.» · [[2026-10-14 Email – AW Offerte Wartungsvertrag 2027]] · medium

## History
- 2026-10-14 · created: no candidate matched hans.mueller@acme-ag.example · [[2026-10-14 Email – AW Offerte Wartungsvertrag 2027]]
```

The file name is the note's name and link target, unique across the vault; its identity is the `id`, which never
changes. Front matter is flat (`key: value` lines and block lists), so YAML parsers, Obsidian Bases and line-based
readers all read it the same way. `## Notes` is yours: orbit writes to it only to carry it over when two notes are
merged, and to keep its links pointing at renamed notes. An example vault with a note of every type is in
[`tests/vaults/example`](tests/vaults/example); the format is specified in [docs/vault-format.md](docs/vault-format.md).

## Tools

| Tool | What it does |
|---|---|
| `resolve_entity` | Candidates for a person, organization or topic, ranked, with the evidence for each. |
| `get_entity_context` | A note's fields, observations, last field changes, links in and out, recent interactions, open tasks and pending reviews; for an email, its thread with its topics and open tasks. |
| `search_entities` | Full-text and fuzzy search over names, aliases, addresses, domains, job titles and notes. |
| `list_entities` | Queries over front-matter fields: everyone at an organization, open tasks due before a date, people not contacted since. |
| `log_interaction` | An email, meeting, call or message, with its people by name or address; linked to the email it answers, and answered with its thread. Idempotent, and a retry learns what is recorded already. |
| `upsert_person`, `upsert_organization`, `upsert_topic` | Create a record, or add to one: lists merged, empty fields filled, conflicts reported. A new one too like one there is refused, unless it is said to be another (`distinct_from`). |
| `link_entities` | Set relations from a fixed vocabulary, one or several at once: `org`, `reports_to`, `colleague_of` (both ways), an interaction's people, … |
| `link_document` | Record a document outside the vault: a URL, a path or an id. |
| `add_observation` | A fact with its evidence quote, source and confidence. |
| `set_fields` | Change fields with a dated history line; a change older than the stored value becomes an observation instead. Takes items out of lists too (a wrong address, a former organization no one stated). |
| `create_task`, `update_task` | What you promised, what was asked of you, and what others promised you; a task like an open one of the same thread is refused until confirmed. |
| `propose_review` | A question for you, answered in Obsidian: a duplicate (people, organizations, topics) decided `same` (or `yes`) is merged, one decided `different` (or `no`) is recorded on both notes; an address confirmed is added, a job change confirmed is made. An open question you answer in your own words, for an agent to act on. |
| `settle_review` | What an agent did with your answer, recorded on the review, once. |
| `merge_entities` | Two notes about the same person, organization or topic become one; links follow, differing values go to review. |
| `rename_entity` | A new name and file name; every link to the note follows. |
| `create_missing_references` | Notes for links to notes that don't exist yet: mapped to an alias, or a stub of the type the link's field asks for. |
| `lint_vault` | Schema conformance, duplicate ids and addresses, clashing file names, broken links, unknown fields; `fix` repairs the safe cases. |

Every write names its `source`, returns the ids and absolute paths of the notes it changed, and does nothing when
called again with the same arguments, where it can. Errors say what to do next. Every parameter is described in the
tools' schemas, for the agents that read them.

## Commands

| Command | What it does |
|---|---|
| `orbit init [VAULT]` | Create a vault, or add what one lacks: its folders, `Me.md`, `99_System` and the Bases views. |
| `orbit serve [VAULT]` | Serve the vault over MCP (`--stdio`, `--host`, `--port`, `--tools`), watching it for edits made elsewhere. |
| `orbit lint [VAULT]` | Check the vault (`--fix`, `--json`); exits with 1 if errors remain. |
| `orbit reindex [VAULT]` | Build the index again from the notes. |
| `orbit status [VAULT]` | Notes per type, pending reviews, clashes and the index, also while a server runs. |

`VAULT` defaults to the current folder. Results go to stdout; everything else orbit says goes to stderr.

## Configuration

`99_System/orbit.toml`, written by `orbit init`:

| Setting | Default | |
|---|---|---|
| `me` | the id of `Me.md` | Your own note, which your addresses resolve to. |
| `server.host`, `server.port` | `127.0.0.1`, `8775` | Where `orbit serve` listens. It warns when told to listen beyond this machine. |
| `server.tools` | all | The tool groups (`read`, `write`, `upkeep`) or tools that `/mcp` offers; `/mcp/write` and `/mcp/read` offer less. |
| `identity.free_mail_domains` | gmail.com, outlook.com, gmx.ch, bluewin.ch, … | Domains that say nothing about an employer. |
| `identity.role_addresses` | info, noreply, team, sales, support, … | Mailboxes that never belong to a person. |

`99_System/nicknames.txt` lists first names that stand for one another, one group per line: `Hans = Hansi =
Hansruedi`. The one environment variable, `ORBIT_HOME` (default `~/.orbit/`), says where the indexes live: outside
the vault, one database per vault, so sync tools never see a live database.

## How it works

- **Reading and writing.** Anything may read the vault. Agents write through orbit's tools, which check the index,
  read the note again (an edit made by hand may not be indexed yet), write it atomically (a temporary file, then a
  rename), and update the index in the same call. Tools run one at a time, and one orbit process at a time may open a
  vault, so nothing writes concurrently.
- **The index** holds ids, paths and front matter; addresses, domains, name keys and sound-alike codes; links both ways;
  field changes from the History sections; and full-text search. Its unique indexes on ids, file names, people's
  addresses and message ids make duplicates impossible through orbit; a hand edit that breaks one is recorded as a
  clash, which `lint_vault` reports, instead of stopping the index.
- **Duplicates.** Names are compared without case, accents or word order (ä as ae, titles dropped), with initials,
  nicknames and Kölner Phonetik; addresses exactly; organizations by domain, Swiss UID and name without legal form.
  orbit ranks the candidates; the agent decides, or asks you through a review.

## Scope

In scope: one owner's network, in Markdown files on their machine; any number of local agents; Linux, macOS and
Windows. Out of scope, by design: an LLM inside orbit, network access and cloud services, reading mailboxes or the
web (agents that do so use orbit's tools), authentication, and legal or compliance features.

## Versioning

orbit is in early development (0.x): the vault format, the index, the tools and the Bases views work and are tested,
and minor versions may still change the tools and the format. From 1.0, it follows
[semantic versioning](https://semver.org/): within a major version, the vault format, the MCP tools and their
parameters, the commands and their JSON output, and `orbit.toml` stay compatible. The index is derived and rebuilt
when its layout changes, so it never needs migrating. The [changelog](CHANGELOG.md) lists every change.

## Development

```bash
git clone https://github.com/tobiaswuerth/orbit
cd orbit
uv sync                     # the virtual environment, with the development tools
uv run pre-commit install   # lint, format and config checks on every commit
uv run pytest --cov         # 100% line and branch coverage is required
```

The tests use temporary vaults and a temporary `ORBIT_HOME`, and run the MCP server for real, in memory. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the code layout and how changes are made, and [SECURITY.md](SECURITY.md) for
reporting vulnerabilities.

## License

[MIT](LICENSE)
