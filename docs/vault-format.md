# The vault format

What orbit writes, and what it expects when it reads notes edited by hand. The example vault in
[`tests/vaults/example`](../tests/vaults/example) shows every note type; the tests hold orbit to it.

## Layout

| Folder | Notes |
|---|---|
| `01_People/` | One note per person, `Hans Müller.md`; `Me.md` is the vault's owner, with `me: true` |
| `02_Organizations/` | `Acme AG.md` |
| `03_Interactions/YYYY/YYYY-MM/` | `2026-10-14 Email – AW Offerte Wartungsvertrag 2027.md`: date, kind, subject |
| `04_Tasks/` | `Send revised offer for Wartungsvertrag 2027.md` |
| `05_Topics/` | Projects, deals in progress, recurring themes |
| `90_Review/` | Questions for the owner: `2026-10-18 Duplicate – Hans and Hans Müller.md` |
| `95_Bases/` | Obsidian Bases views `orbit init` writes: `People.base`, `Follow-ups.base`, `Review.base` |
| `99_System/` | `orbit.toml`, `nicknames.txt`, and `AGENTS.md` for agents that read the vault |

Folders whose names start with a dot, `95_Bases/` and `99_System/` hold no notes. Markdown files elsewhere are indexed
too, so that links to them resolve, but only notes with a `type` are entities.

## Names and ids

- **The file name is the note's name and link target**: `[[Hans Müller]]`. File names are unique across the vault,
  compared as links compare them (any case, any Unicode form), so a link never depends on a folder. A note's `name`
  is its file's: `rename_entity` changes both, and `lint_vault` names a note whose `name` went its own way.
- On a clash, orbit adds a distinguisher, `Hans Müller (Acme AG).md`, or else a number, `Hans Müller (2).md`, and
  keeps the plain name in `aliases`. A long name is first cut at a word, to 120 characters and 240 bytes of UTF-8,
  so that it fits the limits of every system.
- File names leave out `: / \ ? * " < > |`, which Windows forbids, and `[ ] # ^`, which links use. A name Windows
  reserves, alone or with an extension, gets an underscore: `CON_`, `Con_.Inc`.
- **Identity is the `id`**: a type prefix (`per_`, `org_`, `int_`, `tsk_`, `top_`, `rev_`) and a
  [ULID](https://github.com/ulid/spec), whose time is when the note was created. Ids never change and are never reused.

## Front matter

- Flat `key: value` lines; lists as block lists, one `- item` per line; `key: []` for an empty list.
- No nested mappings, flow lists with items, multi-line strings, anchors or tags: orbit refuses to read them, with the
  line, rather than read them differently from a YAML parser.
- Wikilinks are always quoted: `org: "[[Acme AG]]"`.
- Dates are `YYYY-MM-DD`; times are ISO 8601 with their offset, `2026-10-14T09:32:00+02:00`.
- orbit quotes every value that YAML would read as something else: one with `: ` or `#`, one that starts with a
  special character, and one that looks like a number, a boolean or null (`"8400"`, `"yes"`). Every note orbit writes
  reads back as the same values with a full YAML parser.
- No `title` field on any type: the file name is the title. Body headings start at `##`.
- orbit writes fields in the schema's order and never adds fields outside it. Fields added by hand are kept, as
  written, after the schema's; `lint_vault` lists them.

## Fields

| Type | Fields |
|---|---|
| person | `type`, `id`, `name`, `me`, `aliases`, `emails`, `phones`, `org`, `job_title`, `department`, `former_orgs`, `reports_to`, `assistant_of`, `colleague_of`, `introduced_by`, `context` (professional, personal, both), `languages`, `salutation` (du, Sie), `location`, `last_contact`, `next_followup`, `review_status` (confirmed, needs_review), `merged_from`, `distinct_from`, `documents`, `created`, `updated` |
| organization | `type`, `id`, `name`, `aliases`, `domains`, `uid_che`, `industry`, `location`, `address`, `website`, `parent`, `relationship` (client, prospect, partner, vendor, employer, personal), `merged_from`, `distinct_from`, `documents`, `created`, `updated` |
| interaction | `type`, `id`, `kind` (email, meeting, call, message, note, automated), `date`, `direction` (inbound, outbound), `subject`, `from`, `to`, `cc`, `participants`, `mentioned`, `orgs`, `topics`, `language`, `message_id`, `in_reply_to`, `replies_to`, `thread`, `source_file`, `sha256`, `documents`, `created` |
| task | `type`, `id`, `status` (open, waiting, done, cancelled), `due`, `due_note`, `owner`, `related`, `origin`, `cancel`, `created`, `updated` |
| topic | `type`, `id`, `name`, `aliases`, `status` (active, paused, closed), `orgs`, `people`, `documents`, `merged_from`, `distinct_from`, `created`, `updated` |
| review | `type`, `id`, `kind` (duplicate, job_change, address, other, question), `question`, `candidates`, `address`, `decision` (pending, same, different, yes, no, answered), `answer_yes`, `answer_no`, `answer`, `applied`, `source`, `created` |

Relations are fields holding wikilinks, never nested mappings. `documents` refers to documents outside the vault, each
as a Markdown link with its title: `"[Offer v2](https://…)"`, or `"[Offer](<C:\Offers\Offer v2.pdf>)"` for a
reference with spaces. orbit sets `id`, `type`, `created`, `updated`, `me`, `last_contact`, `merged_from`,
`distinct_from`, `documents` and `replies_to` itself.

An interaction's `source_file` is where its original is kept, as the caller gave it. The original's file names its
interaction wherever a source is asked for, in any spelling of the path.

An email's `thread` is the message id of the thread's first email, from its `References` or `In-Reply-To`.
`replies_to` links the interaction it answers: the one whose `message_id` its `In-Reply-To` names, or else the
latest of its `References` in the vault; an email logged after its replies is linked from them then.

## Body sections

orbit only touches the sections it manages, and leaves every other byte of a note as it was. Text a caller gives
keeps to its section: in a summary, a line that would open a heading or a code fence is escaped with a backslash
(`\## …`), which Markdown shows the same, and evidence, decisions and observations keep to one line each.

| Type | Sections |
|---|---|
| person, organization, topic | `## Notes` (the owner's own: orbit writes to it only to carry it over in a merge, and to keep its links pointing at renamed notes), `## Observations` and `## History` (append-only, but for an observation taken back, which moves to History), `## Documents` |
| interaction | `## Summary`, `## Decisions`, `## Action items` (links to its tasks), `## Key quote`, `## Documents`, `## Original` (a link to its `source_file`, when that is a local file) |

A document or original that is a local file (`C:\…`, `/home/…`) is linked in the body as a `file://` URL,
`- [Offer v2](file:///C:/Offers/Offer%20v2.pdf)`, which Obsidian opens with the file's program; the `documents` field
keeps the path as given. Only documents, pictures and recordings are linked (`.pdf`, `.docx`, `.md`, `.eml`, `.jpg`,
…): a click must not run a program, and a file on another computer (`\\server\share\…`) would be sent the owner's
Windows credentials. A relative path stays as it is: orbit can't tell what it is relative to.
| task | `## Details` (the commitment as stated, then a line per update), `## Notes` |
| review | `## Evidence for`, `## Evidence against`, `## How to answer`; once an answer is acted on, `## Applied` (what was done with it) |

Observations and history lines carry their date and their source: an interaction's link, or a short description such
as `Tobias in chat, 2026-10-22`.

```
- 2026-10-14 · <fact> · «<the source's words>» · [[<source>]] · high
- 2026-11-20 · job_title: Leiter Einkauf → Head of Procurement · [[<source>]]
- 2026-11-20 · location: Winterthur · [[<source>]]
- 2026-10-14 · created: <why the note was created> · [[<source>]]
- 2026-10-24 · retracted: 2026-10-14 · <fact> · «<the source's words>» · [[<source>]] · high → <why it isn't so> · <who took it back>
```

Confidence is `high` (stated outright) or `medium` (clearly implied). Text in these lines has no « », " · " or " → " of
its own: they become ‹ ›, ", " and " -> ". History lines record single-value fields: set, changed, or cleared (`→
""`), and items taken out of a list (`emails: old@acme.example → ""`). Their dates let orbit tell whether a new value
is newer than the stored one. An observation taken back (`retract_observation`) leaves Observations for a `retracted:`
line in History, which holds its line whole, why, and who took it back, dated like every history line by its source
(today, for a source in words). It isn't recorded again from the same source or with the same words, and a merge
doesn't bring it back from the other note. A person's `org` changed by another source than the one that set it moves
the old one to `former_orgs`; changed by the same source, it is a correction and moves nothing.

## Tasks

An open or waiting task has a Cancel box (`cancel: false`), which the Follow-ups base shows. Ticked, orbit cancels the
task the next time it reads the note, and its Details say so with the day (`status: waiting → cancelled · the owner's
Cancel box`); a closed task has no box. `orbit close-tasks --before DAY` ticks the boxes of the open and waiting tasks
from interactions dated before a day (or, from none, created before it), for many at once.

## Reviews

A review asks the owner one question. A yes-or-no question they answer in Obsidian with one click, ticking Yes or No
in the Review base (its `answer_yes` and `answer_no` boxes), or by setting `decision`; orbit sets the decision the box
says and applies it the next time it reads the note. Both boxes ticked is no answer, which `lint_vault` lists. An
address answered yes that another person's note has brings a duplicate review of the two: its yes merges them, and the
address follows. For a
duplicate, No (`different`) adds each note to the other's `distinct_from`, and confirms a provisional person
(`review_status: needs_review`); Yes (`same`) merges the newer note into the older one, also where an agent recorded
the two as different: the owner's answer wins over an agent's, and each note's history says so (`distinct_from: Hans
→ ""`). Only an owner who answered the same pair different in another review is asked to settle which holds. A
decision that can't be applied is listed by `lint_vault`. Reviews written before the boxes get them when orbit next
reads the vault.

An open question (`kind: question`) asks what only the owner can tell, such as whether an organization is their bank
or who a person was to them. The owner answers in their own words in its `answer` property, which the Review base's
table shows as a column to type into; orbit then sets `decision` to `answered`. An agent that acts on the answer
(recording a fact with the owner as its source, correcting a note) records what it did with `settle_review`: a line
under `## Applied`, and the `applied` date, so that no one acts on it twice. Any answered review can be settled so.

What a review asks is asked once: proposing it again returns it, pending or answered, with the owner's answer.

## Merging and renaming

- **A merge** keeps one note under its name and the older of the two ids; the other id goes to `merged_from`, and
  still finds the note. Lists are united, blank fields filled, observations, documents and history lines carried
  over, and the merged note's name kept in `aliases`. Where the two hold different values, the kept note's stay, and
  a review asks whether they are right. The owner's own sections are carried over below a line `From <name>, merged
  on <date>:`. A history line records the merge: `- 2026-10-22 · merged: Hans (per_…) · <source>`.
- **The merged note** goes to `.trash/` in the vault, as Obsidian deletes notes, from where it can be restored.
- **Links follow** a merged or renamed note everywhere: in front matter and in the body, with any path, heading,
  block or display text they had. A renamed person, organization or topic gets its new `name`, with a history line,
  and keeps its old name in `aliases`.
