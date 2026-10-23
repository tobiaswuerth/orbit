# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.8.0] - 2026-10-23

The owner's answers win, and take a click; people at their organization; organizations that owe tasks.

### Added

- Yes-or-no reviews have two boxes, `answer_yes` and `answer_no`, which the Review base shows as Yes and No to tick
  with one click, and a "How to answer" column. orbit sets the decision the ticked box says. Pending reviews written
  before get the boxes when orbit next reads the vault. In an existing vault, `orbit init` leaves your `Review.base`
  as it is: delete it and run `orbit init` to get the new one.
- A person given no organization, with none yet, gets the one their address is at: the organization whose domains
  hold its domain, or the nearest domain it is under (`students.school.example` is `school.example`'s).
  `upsert_person` says so in `org_from_domain`. Never by a free-mail domain, never for the owner.
- `link_by_domain` (upkeep) links the people already in the vault so, each with a history line naming the address,
  dated by their last contact, so that a later email still changes it.
- `resolve_entity` finds an organization by a subdomain of its domain.
- `log_interaction` answers with `open_tasks`: the open tasks of the people and organizations the interaction is with,
  which it may settle; up to 50, and `open_tasks_more` counts the rest.
- `orbit serve` writes each run's log, every line with its time, to `ORBIT_HOME/logs/serve-<time>.log`, down to how
  it ended (an error, or stopped by hand); every log is kept.

### Changed

- The owner's yes to a duplicate review merges the two notes even where an agent recorded them as different
  (`distinct_from`): the record comes off both, with a history line. Only where the owner answered the same pair
  different in another review is the yes left, and `lint_vault` asks which holds. `merge_entities` still refuses such
  notes, and says that only the owner's answer merges them.
- `propose_review` returns the review that asks the same already, answered or not, with the owner's `decision` and
  `answer`, rather than asking again. Open questions and other yes-or-no reviews ask the same when their words do.
- A task's owner may be an organization: a shop's refund, a provider's fix.

### Fixed

- `upsert_person` refuses `provisional` together with `distinct_from`, which said at once that a person may be
  someone and isn't, so that the owner's answer couldn't merge them.
- Two duplicate reviews of one pair, both answered yes, merge it once; the second no longer reports that it couldn't
  merge the note with itself.

## [0.7.1] - 2026-10-23

### Changed

- Tool descriptions and tests use made-up examples only. Releases 0.5.0 to 0.7.0 are no longer on PyPI.

## [0.7.0] - 2026-10-23

### Changed

- An open question's answer goes in its `answer` property, which the Review base's table shows as a column to type
  into: Obsidian's tables edit properties, not a note's body. The `## Answer` section is gone. `orbit init` writes the
  column into a new vault's `Review.base`; in an existing vault, add `answer` to the views of yours.

### Fixed

- On macOS, a change to the vault's folder itself, as the system reports it, made the watcher sync the whole index;
  it is passed over now.

## [0.6.0] - 2026-10-23

Questions only the owner can answer, and answers in their own words.

### Added

- Open questions: `propose_review` with kind `question` asks what no source says (is this organization the owner's
  bank? who was this person to them?). The owner answers under the note's `## Answer`, in words; orbit sets its
  `decision` to `answered`, so agents find it (`list_entities` of reviews) and read the answer
  (`get_entity_context`).
- `settle_review`: what an agent did with an answer, as a line under `## Applied` and the `applied` date, once; for
  any answered review.

## [0.5.0] - 2026-10-23

What a review of 100 imports by a stronger model couldn't fix.

### Added

- `set_fields` takes items out of list fields: `remove: {"emails": ["old@acme.example"]}`, each with a line in the
  history, and `removed` in the answer says what came out. A colleague comes out of both notes. orbit's own lists
  (`merged_from`, `distinct_from`, `documents`) stay orbit's.

### Fixed

- A person's org that the same source set before, when the note was created or since, and now sets again or clears,
  is a correction: the old one no longer joins `former_orgs`. An import that set an org on a guess and took it back
  had left an employment no one stated.

## [0.4.1] - 2026-10-23

### Fixed

- Evidence from an email's quoted history was refused when it ran over two quoted lines: the `>` each line starts
  with stood between its words. The markers are set aside now, nested ones too.

## [0.4.0] - 2026-10-23

Duplicates prevented where they come about, answers that act, and evidence kept as written: what importing 600 real
emails, 20 at a time, showed.

### Added

- A new person, organization or topic too like one already there is refused when it is created, with the notes it
  is like and their scores: a person of the same full name, an organization whose name starts with another's or is
  its initials (AZO, Ausbildungszentrum Zürcher Oberland), a topic sharing most of its words with another. The
  caller passes the one it means as `match`, or `distinct_from` with the ones it is not, which is recorded on both;
  a person it is unsure of is still created `provisional`. orbit takes calls one at a time, so two callers that
  create one note at once make one: in that import, two runs had created "Modulprüfung MP 254" and "Modulprüfung
  Modul 254".
- Reviews whose answers act: an address review (`kind: address`, with `address`) adds the address to the person on
  yes; a job change about a person and an organization makes it theirs on yes, the one before a former one. Both are
  applied once and marked `applied`, so that a later hand edit stays. Two topics can be asked about as duplicates
  and merged. `get_entity_context` lists the answered reviews about a note: agents had asked twice whether an
  address was the owner's, as the first yes did nothing.
- Evidence is checked when it is written: an observation's quote must be in the file its interaction was logged
  from, or a text document linked from it, as written (case, spaces, quotation marks and emphasis aside); parts
  that aren't together are joined with …. In the import, 9% of the quotes had been shortened or reworded unmarked.
- A note is found by its `name` field or an alias, when one note alone has it: Me by the owner's name, a renamed
  note by its old name.

### Changed

- A note of the wrong type linked to an interaction or a topic says where it belongs: an organization named as a
  sender goes under `orgs`. About 10 calls in the import had been refused without saying so.
- `resolve_entity` scores an organization whose name starts with another's, or is its initials, 0.75, and a topic
  sharing at least half its words with another 0.7 to 0.9.
- The index is built again on the first start, for the initials of organizations.

## [0.3.1] - 2026-10-23

### Fixed

- A duplicate review answered `yes` or `no`, as owners answer "Is Hans the same person as Hans Müller?", was left as
  it was, and agents asked about the pair again; `yes` merges the two now, as `same` does, and `no` records them as
  different.
- Naming a person by a role address, such as `support@`, said to create the person with `upsert_person`, which then
  refuses it; it says now that the address belongs to no person.

### Changed

- `orbit init` says when `Me.md` has no email address, as orbit then takes the owner's own address for a stranger's
  in every mail, and that `--name` and `--email` change nothing on a vault that has a `Me.md` already.

## [0.3.0] - 2026-10-23

What logging real mail showed: calls refused for what didn't exist yet, sources that were file paths, the same fact
twice, notes Obsidian couldn't open, and a watcher woken by Obsidian itself. The index is rebuilt by itself on the
first start.

### Added

- `log_interaction` logs the interaction even when organizations, topics or people it names don't exist yet: they
  are listed under `unknown_orgs`, `unknown_topics` and `unknown_people`, as unknown addresses are, to be created
  with the interaction as their source.
- The file an interaction was logged from (its `source_file`) names that interaction wherever a source is asked for,
  in any spelling of the path; another absolute path is refused as a source, with what to do instead.
- An interaction whose `source_file` is a local file links it in a new `## Original` section, and documents that are
  local files are linked in the body as `file://` URLs: Obsidian opens them with a click. Only documents, pictures
  and recordings on the same computer are linked, never programs or files on a share.
- The resource `orbit://vault` on every endpoint: the vault's folder, orbit's version and its notes by type, as
  JSON, for programs that need to know what a server serves.

### Changed

- `add_observation` records the same evidence from another source once: an email sent twice, or a fact repeated in
  a reply's quoted history, no longer gives the same observation twice.
- A clearing that `set_fields` doesn't apply (older than the stored value) is listed under `not_applied`, without an
  observation.

### Fixed

- The watcher leaves out hidden folders: Obsidian rewrites `.obsidian/workspace.json` whenever a note is opened,
  which woke the watcher and logged "1 change detected" each time.

## [0.2.0] - 2026-10-22

For agents that log mail: narrower tool surfaces by URL, threads, fewer calls per email, no duplicate tasks for a
repeated commitment, and retries that know what is recorded. The index is rebuilt by itself on the first start;
interactions logged before keep no `replies_to`, and their threads are shown all the same.

### Added

- Tool profiles: the tools come in groups (`read`, `write`, `upkeep`), and orbit.toml's `server.tools` or
  `orbit serve --tools read,write` names those to serve. Over HTTP, `/mcp/write` offers them without upkeep and
  `/mcp/read` only the read tools, so a client gets a safe surface by its URL beside the owner's full `/mcp`.
- Threads: an email that answers one in the vault links it in `replies_to` (from `in_reply_to`, or the latest known
  of `references`; an email logged after its replies is linked from them then). `get_entity_context` of an
  interaction, and `log_interaction`'s answer, show its thread: its interactions, their topics and open tasks.
- `link_entities` takes several links at once (`links`), each checked before any is written; a person may be named
  by an email address wherever a note is named. Addresses may be written as an email's headers write them:
  `"Müller, Hans" <hans.mueller@acme-ag.example>`.
- `log_interaction` takes the addresses of an email's headers: known people are linked, the others are listed under
  `unknown_addresses` (and `role_addresses`) instead of failing the call.
- `create_task` refuses a task like an open one of the same thread, or of the same owner and matter, and names it;
  `match: "new"` creates it anyway, `match` with its id returns that task.
- Logging an interaction again answers what it holds already (`recorded`), so a retry adds only what is missing.

### Fixed

- `propose_review` finds the pending review that asks about the same notes however its candidates are written
  (`[[hans müller]]`), as links compare names, instead of asking again.

## [0.1.1] - 2026-10-22

Fixes from a review of the whole code base: most for notes edited by hand, for repeated calls, and for Windows.

### Fixed

- `resolve_entity` finds an organization by a Swiss UID written without its separators (`CHE123456789`) or with
  a suffix (`CHE-123.456.789 MWST`); the index is rebuilt once, by itself, to match.
- A tab after spaces at the start of a front-matter line is reported as a tab, not as a nested mapping.
- Repeating a call is safe: `log_interaction` without a message id, and `upsert_*` with "new", return the note the
  first call made instead of a second one (`Lea Frei (2)`), as an agent retrying after a timeout needs. A new
  topic named like an existing one is that one.
- `get_entity_context` and the write tools name the note and say what to do when it is gone, unreadable or not
  UTF-8, instead of a bare file error; `match` takes "new" in any case; a `limit` below zero means none.
- Text an agent gives can't break a note's sections: a summary's lines that would open a heading or a code fence
  are escaped (`\## …`, as Markdown allows), and each piece of a review's evidence keeps to one line.
- Addresses and domains with umlauts (`hans@müller.ch`, `bücher.ch`) are valid; a web address with a login or a
  port gives its domain; a note named like a name Windows reserves, with an extension too (`Con.Inc`), gets a
  file name Windows allows.
- A merge or rename no longer stops halfway at a note that can't be read: it rewrites every link it can and lists
  the rest under `links_left`, with the reason. The index takes the links of a note whose front matter can't
  be read from its text, so they are followed and checked. Merging a note without an id says to give it one.
- The `orbit` command reports a file-system error in one line, and stops quietly on Ctrl+C. `orbit serve --port`
  refuses what isn't a port number, as `orbit.toml` does, instead of failing on it when the server starts.
- A damaged index file is built again from the notes, instead of keeping orbit from starting.
- `orbit.toml` and `nicknames.txt` saved with a byte order mark (as PowerShell writes UTF-8) are read; either file
  in another encoding is named in the error. A note deleted while the vault is listed no longer fails the sync.
- `orbit init` on a vault whose `Me.md` has no id says so instead of failing with a traceback, and only needs that
  id when it writes `orbit.toml`.
- A link to a file that isn't a note, such as an embedded Bases view (`![[Follow-ups.base]]`) or `[[AGENTS]]`, is
  no longer a broken link to `lint_vault`, nor a note `create_missing_references` asks to create.
- An index file that can't be opened at all fails with the file system's error, not an unrelated one.
- A second note with a long name, such as the next reply in a thread with a long subject on the same day, gets
  ` (2)` instead of failing with "too many notes are called …": shortening the name cut the number off again. Long
  names in scripts of several bytes per letter, or with emoji, are cut to fit Linux's and macOS' 255 bytes.
- `create_missing_references` lists the notes it couldn't rewrite under `links_left`, as merges and renames do,
  instead of counting them as mapped. Renaming a note, and moving one to `.trash`, wait a little for a file another
  program has open, as writes do.
- The `propose_review` tool says that a duplicate decided "same" is merged.
- `ORBIT_HOME=~/…`, as an MCP client's `env` or PowerShell passes it on, is under the home folder, not in a folder
  called `~` wherever orbit was started. So is a vault given as `~/crm` on the command line, which PowerShell and cmd
  pass on as it is: `orbit init ~/crm`, as the README writes it, no longer creates a folder called `~`.
- `set_fields` no longer clears fields orbit sets itself, such as `id` or `type`, when given null for them, nor fields
  outside the schema or a note's `name`: it refuses them, as it refuses setting them.
- An unexpected error while indexing an edit made elsewhere is logged with its traceback, and `orbit serve` keeps
  running, instead of stopping with the watcher.
- A list item left empty by a hand edit, in a note's `aliases` or `domains`, no longer makes `resolve_entity` fail
  for every query that finds the note, nor one in `documents` `link_document`. Every tool is now tested on notes
  whose fields a hand edit left empty, in the wrong shape or as booleans.
- An interaction whose `date` a hand edit broke no longer fails `link_entities`, nor writes its text into a
  person's `last_contact`; an `org` made a list moves to `former_orgs` item by item.
- Front matter list items are read as YAML reads them: `- [[Acme AG]]` unquoted, which YAML reads as a list in a
  list, is refused with "quote a wikilink" (and so is `org: [[Acme AG]]`, which said "write lists as block lists"),
  `- #tag` is an empty item, and `- [x]`, `- {…}`, `- |` are refused as values are. A key followed by spaces
  takes the list below it.

### Changed

- The instructions agents receive say when to merge, and what tools do to the owner's Notes. Without the owner's
  name, they speak of "the vault's owner", not "the owner, the vault's owner".
- The README installs and updates orbit from PyPI (`uv tool install orbit-crm`).

## [0.1.0] - 2026-10-22

The first release: a personal CRM as a vault of Markdown notes, kept by a local MCP server. It covers the three phases
of the plan: storage and the index, the tools agents use, and upkeep.

### Added

- Releases: once CI has passed on a commit of `main` whose version has a section here and no tag yet, it is
  published to PyPI as `orbit-crm` and tagged, with a GitHub release (see "Releasing" in CONTRIBUTING.md).
- The README explains setting up the MCP server locally (HTTP or stdio), updating, how orbit works, and its scope
  and versioning.
- `merge_entities`: two notes about the same person, organization or topic become one. Lists are united, blank fields
  filled, observations and history carried over, the older id kept and the other recorded in `merged_from`, where it
  still finds the note; values that differ stay as they were and go to a review. Every link is rewritten, and the
  merged note goes to the vault's `.trash`. A duplicate review decided `same` in Obsidian is merged this way.
- A benchmark on a generated vault of 5,000 people and 50,000 interactions ([docs/benchmarks.md](docs/benchmarks.md)):
  the index builds in 14 s, orbit starts in under a second with it up to date, and tools answer in milliseconds.
- Obsidian Bases views, written by `orbit init` to `95_Bases/` where none are: People (everyone, by organization,
  not contacted for a year, to confirm), Follow-ups (open tasks, tasks others owe, people to follow up) and Review
  (pending and answered).
- `create_missing_references`: a link to a note that doesn't exist is rewritten to the note whose alias it names,
  or gets a stub note of the type its field asks for; what can't be decided is listed with the reason.
- `rename_entity`: a note gets a new name and file name, and every link to it, in front matter and body, follows.
- `orbit serve`: an MCP server over streamable HTTP (`127.0.0.1:8775` by default) or `--stdio`, with instructions
  that tell connecting agents the rules, and the vault watched for edits made elsewhere while it runs. It warns when
  told to listen beyond this machine.
- Read tools: `resolve_entity` (ranked candidates with their evidence: email address, phone, name in any order or
  spelling, alias, initials, nickname, sound-alike surname, company domain, organization, job title; Me for the
  owner's own addresses; pairs marked different flagged), `get_entity_context`, `search_entities` and
  `list_entities`.
- Write tools: `log_interaction` (idempotent on the message id, threads, `last_contact`), `upsert_person`,
  `upsert_organization` and `upsert_topic` (lists merged, empty fields filled, conflicts reported; "new" refused for a
  known address, domain or UID; role addresses and free-mail domains refused), `link_entities` (a fixed vocabulary
  of relations, colleagues both ways, a changed org moved to `former_orgs`), `link_document`, `add_observation`,
  `set_fields` (dated history lines; a change older than the stored value becomes an observation), `create_task` and
  `update_task`. Every write names its source and returns the ids and paths of the notes it changed.
- Reviews: `propose_review` writes a question for the owner; a duplicate decided `different` in Obsidian is recorded
  as `distinct_from` on both notes, and confirms a provisional person.
- `lint_vault` and `orbit lint`: unreadable notes, schema problems, missing ids, clashing ids, addresses and file
  names, broken links, unknown fields, notes in the wrong folder; `fix` assigns missing ids and lowercases addresses.
- The vault format: one Markdown note per person, organization, interaction, task, topic and review, with flat front
  matter, ids of a type prefix and a ULID, and file names unique across the vault and safe on every system.
- Front matter read and written by orbit's own strict reader and writer of flat YAML: `key: value` lines and block
  lists. It refuses what a YAML parser would read differently, quotes every value YAML would read as something else,
  and leaves the fields and lines it doesn't change as they were written.
- The schema of each note type: its fields in order, their kinds (dates, times with offsets, wikilinks, addresses,
  domains, choices), required fields, and its body's sections.
- Name keys for duplicate detection: Unicode folding with umlauts as ae, oe and ue, word order and titles ignored,
  initials, nicknames from `99_System/nicknames.txt`, Kölner Phonetik, organization names without their legal form,
  and phone numbers however they are written.
- The index, a SQLite database in `ORBIT_HOME` (default `~/.orbit/`), derived from the notes alone: ids, paths and
  front matter, addresses, domains and name keys, links both ways, field changes from History sections, and full-text
  search. Unique indexes on ids, file names, people's email addresses and message ids; a hand edit that breaks one is
  recorded as a clash instead of stopping the index. Brought up to date incrementally, by modification time, size and
  hash, and built again when its layout changes.
- A file watcher that puts notes edited in Obsidian into the index within a second.
- One writer per vault: a lock in `ORBIT_HOME` refuses a second orbit process.
- `orbit init`: a vault's folders, `Me.md`, `orbit.toml`, `nicknames.txt` and `AGENTS.md`.
- `orbit reindex`: the index built again from the notes.
- `orbit status`: notes per type, pending reviews, clashes and unreadable notes, also while a server runs.
- The project: package `orbit-crm` with the `orbit` command, tests with 100% line and branch coverage, pre-commit
  hooks, and CI on Linux, macOS and Windows for Python 3.11 to 3.15.
