# Contributing

Thanks for helping. Bug reports and feature ideas are welcome as [issues](https://github.com/tobiaswuerth/orbit/issues);
for security problems, see [SECURITY.md](SECURITY.md).

## Setup

```bash
git clone https://github.com/tobiaswuerth/orbit
cd orbit
uv sync
uv run pre-commit install
uv run pytest --cov
```

Read [docs/vault-format.md](docs/vault-format.md) first: it specifies the notes orbit reads and writes, which every
change keeps to. The README's "Scope" says what orbit is for and what it leaves out.

## Code layout

| Module | What it does |
|---|---|
| `cli.py` | The `orbit` command |
| `server.py` | `orbit serve`: the MCP tools, their descriptions for agents, and the HTTP and stdio transports |
| `crm.py` | A vault opened for work: the one-writer lock, the index kept fresh, finding notes, and the write order every tool follows |
| `resolve.py` | `resolve_entity`: candidates and their evidence |
| `reads.py` | `get_entity_context`, `search_entities`, `list_entities` |
| `writes.py` | The write tools |
| `reviews.py` | `propose_review` |
| `upkeep.py` | `merge_entities`, `rename_entity`, `create_missing_references`, the links that follow them, and applying the decisions set on reviews |
| `lint.py` | `lint_vault` |
| `edits.py` | Field changes every write makes the same way: adding to lists, setting values with history |
| `index.py` | The SQLite index: layout, incremental sync, unique claims and clashes, lookups |
| `watch.py` | The file watcher that keeps the index fresh while the server runs |
| `vault.py` | Notes as files: listing, reading, atomic writes, renames, `.trash`, `orbit init` |
| `bases.py` | The Obsidian Bases views `orbit init` writes; the views themselves are in `templates/` |
| `schema.py` | The note types: fields, kinds, order, sections, validation |
| `frontmatter.py` | The strict reader and writer of flat front matter |
| `sections.py` | Note bodies as `## ` sections |
| `entries.py` | Observation and history lines |
| `names.py` | Name keys, Kölner Phonetik, addresses, domains, phone keys, safe file names |
| `ids.py` | Ids: a type prefix and a ULID |
| `config.py` | `99_System/orbit.toml` |
| `settings.py` | `ORBIT_HOME`, the one environment variable, read once |
| `console.py` | What orbit tells the user, on stderr |
| `errors.py` | `OrbitError`: an error whose message says what to do next, which tools and commands report as it is |

The notes are the source of truth; the index is derived from them and never holds anything they don't. Every write
checks the index, reads the note again, writes it atomically, and updates the index in the same call (`Crm.save`).
Tools run one at a time on the server's event loop, and the watcher runs on the same loop, so nothing writes
concurrently. No module reads the environment except `settings.py`; results go to stdout from `cli.py` alone.

`benchmarks/` generates a large vault and measures orbit on it; see [docs/benchmarks.md](docs/benchmarks.md). Give it
`--dir` on a local disk: the first reading of new files can be much slower in some folders, such as the temporary one.

## How changes are made

- **orbit stands alone.** No LLM inside, no network requests, no other service or project to depend on: agents and
  other programs reach orbit through its MCP tools, and orbit knows nothing of them.
- **Tests first.** Write a test that fails for the expected reason, then the least code that makes it pass. Every bug
  fix comes with a regression test; never weaken or skip a test to make a change pass.
- **Full coverage.** `uv run pytest --cov` requires 100% line and branch coverage. Tests use temporary vaults and a
  temporary `ORBIT_HOME`, never real ones, and no network; each has a time limit, so one that hangs fails. Before a
  pull request, run them on the oldest supported Python too:
  `uv run --python 3.11 --isolated --with pytest --with pytest-timeout --with pyyaml pytest -q`.
- **Notes edited by hand** are part of the format: a tool may refuse what it can't use, with an error that says what
  to do, but never fail otherwise (`tests/test_hand_edits.py`).
- **The example vault** in `tests/vaults/example` is the format reference. `test_scenario.py` rebuilds it from an
  empty vault through the tools alone, and requires the same notes byte for byte, apart from ids.
- **Agents read the schemas, not the code.** Every tool and parameter has a description that says what an agent needs
  to know, and errors say what to do next.
- **Quality gates.** pre-commit runs on every commit and again in CI: ruff (lint and format), whitespace and line
  endings, YAML/TOML checks, `validate-pyproject`, workflow and Dependabot schema checks, actionlint and codespell.
  Files are UTF-8 with Unix line ends (`.gitattributes`); some Windows editors and scripts write CRLF or a byte order
  mark, so check the diff after editing with one.
- **Pull requests.** `main` is protected: changes arrive through pull requests, which are squash-merged once every CI
  check passes. CI runs the tests on Linux, macOS and Windows for Python 3.11 to 3.15, and builds and checks the
  package.
- **Changelog.** Note user-visible changes under "Unreleased" in [CHANGELOG.md](CHANGELOG.md), in the
  [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format. Versions follow
  [Semantic Versioning](https://semver.org/); from 1.0, the tools, the vault format and the commands stay compatible
  within a major version.

## Releasing

1. In a pull request, set `version` in `pyproject.toml`, and move the "Unreleased" changes in `CHANGELOG.md` under a
   section for that version, `## [0.2.0] - 2026-11-30`, with its link at the bottom. Run `uv lock` so `uv.lock`
   carries the new version.
2. Merge it. That's all: once CI has passed on the merge commit, the release workflow sees a version with a changelog
   section and no tag, and publishes that commit.
   - It builds the package and publishes it to [PyPI](https://pypi.org/project/orbit-crm/) as `orbit-crm`, through
     trusted publishing (no tokens). The `pypi` environment deploys from `main` only.
   - It tags the commit CI tested `v0.2.0`, and creates a GitHub release with that version's changelog. Release tags
     can't be moved or deleted.
   - It doesn't run the tests itself: it starts only after CI passed on that exact commit, and never for a failed
     run. A version without a changelog section isn't released, so `main` can carry unreleased work.
