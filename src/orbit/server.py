"""`orbit serve`: the MCP server agents keep the CRM through, over streamable HTTP or stdio, with the vault watched
for edits made in Obsidian while it runs."""

import contextlib
import datetime
import json
import logging
import sqlite3
from typing import Annotated, Any, Literal

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.applications import Starlette

from . import __version__, console, lint, logs, reads, resolve, reviews, upkeep, watch, writes
from .crm import Crm
from .errors import OrbitError
from .vault import CONFIG

log = logging.getLogger(__name__)
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
VAULT_RESOURCE = "orbit://vault"  # what the server serves, for programs: folder, version, notes
SHUTDOWN_SECONDS = 3  # how long Ctrl+C waits for open requests before the server stops anyway

# The tools by what they may change, so that an owner can serve some of them: in orbit.toml's [server] tools, with
# `orbit serve --tools`, or to a client that connects to one of the narrower endpoints.
GROUPS = {
    "read": ("resolve_entity", "get_entity_context", "search_entities", "list_entities"),
    "write": (
        "log_interaction",
        "upsert_person",
        "upsert_organization",
        "upsert_topic",
        "link_entities",
        "link_document",
        "add_observation",
        "set_fields",
        "create_task",
        "update_task",
        "propose_review",
        "settle_review",
    ),
    "upkeep": (
        "merge_entities",
        "rename_entity",
        "link_by_domain",
        "create_missing_references",
        "lint_vault",
        "retract_observation",
    ),
}
ENDPOINTS = {"/mcp": None, "/mcp/write": ("read", "write"), "/mcp/read": ("read",)}  # None: all the vault serves

INSTRUCTIONS = """orbit keeps the personal CRM of {whose}: Markdown notes on the people in their
network, their organizations, the owner's interactions with them (emails, meetings, calls), the tasks that come out of
those, and the topics that keep coming back. The owner reads and edits the notes in Obsidian; you read and change them
through these tools.

Rules:
- Resolve before you write. Before creating a person or an organization, call resolve_entity with every name, address
  and domain you have, and read get_entity_context of likely candidates. Then decide: the same (pass its id as
  `match`), a different one (`match: "new"`), or unsure (create it with `provisional: true`, then propose_review, so
  that the owner decides; not with distinct_from, which says you are sure).
- Write only what a source states, and name it. Log an interaction first with log_interaction, then use it as the
  `source` of everything learnt from it; otherwise `source` is a short description such as "{owner} in chat,
  2026-10-22". Don't infer, guess or embellish: a stated fact is an observation, with the words that state it.
- Log an email with the addresses in its headers, and the organizations and topics it concerns; create what its
  answer lists as unknown (people, organizations, topics), with the email as their source, and link them in one
  link_entities call with `links`. Read the thread in the answer before create_task: a commitment repeated in a
  reply is likely an open task already.
- Merge (merge_entities) only notes that the evidence shows are the same; when unsure, propose_review instead, and
  the owner's answer merges them.
- `## Notes` sections are the owner's own: no tool adds to them (a merge carries them over, and links in them follow
  a rename).
- Errors say what to do next: follow them rather than working around them. Repeating a call is safe: it returns what
  the first one made.

Notes are named by their id (per_, org_, int_, tsk_, top_ or rev_ and a ULID) or by their name as links write it,
e.g. "Hans Müller" or "[[Acme AG]]", and people also by an email address; the owner's own note is "Me". Every write
returns the ids and absolute paths of the notes it created or changed, under `changed`.

{vault}"""

# What agents see of the parameters: they read the tools' schemas, not orbit's code.
Ref = Annotated[
    str,
    Field(
        description='A note: its id, e.g. "per_01M4WNN540CGMAHYXV1R90AA5V", its name as links write it, e.g. '
        '"Hans Müller" or "[[Acme AG]]", or a person\'s email address.'
    ),
]
Refs = Annotated[
    list[str] | None,
    Field(description='Notes, each by id, name or, for people, address, e.g. ["Hans Müller", "anna@acme-ag.example"].'),
]
Source = Annotated[
    str,
    Field(
        description="Where the facts come from: the id or [[name]] of the interaction that states them (log it "
        'first), or else a short description, e.g. "the owner in chat, 2026-10-22". The file an interaction was '
        "logged from (its source_file) names that interaction."
    ),
]
Match = Annotated[
    str,
    Field(
        description='The id of the candidate resolve_entity found that this is, or "new" if it is none of them. '
        '"new" is refused if an email address given already belongs to someone, or if a note of the same type is '
        "too alike (same name, initials, most words): the error lists them."
    ),
]
Distinct = Annotated[
    list[str] | None,
    Field(
        description='With "new": the alike notes this is not, by id or name, after checking them. Recorded on both, '
        "so that neither is taken for the other again."
    ),
]
Reason = Annotated[
    str | None,
    Field(
        description='Required for "new": why it is new, e.g. "no candidate matched hans.mueller@acme-ag.example", or '
        '"provisional, possibly [[Hans Müller]]". It is kept in the note\'s history.'
    ),
]
Day = Annotated[str | None, Field(description="A date, YYYY-MM-DD.")]
READ = ToolAnnotations(read_only_hint=True)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True)
APPEND = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False)
DELETE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False)


def _run(fn, *args, **kwargs):
    """Call a tool's function. A failure becomes a ToolError, the only kind whose message reaches the agent: one the
    agent can act on as its message, any other with its type, and with a traceback in the server's log."""
    try:
        return fn(*args, **kwargs)
    except (OrbitError, ValueError, OSError, sqlite3.Error) as e:
        raise ToolError(str(e)) from None
    except Exception as e:
        log.exception("tool failed")
        raise ToolError(f"{type(e).__name__}: {e}") from None


def _owner(crm):
    """The owner's name, from Me.md; None if it isn't known."""
    path = crm.index.holder("id", crm.vault.config.me) if crm.vault.config.me else None
    return crm.entity(path).fields.get("name") if path else None


def _vault(crm):
    counts = crm.index.counts()
    parts = ", ".join(f"{n:,} {t}" for t, n in counts.items() if t) or "no notes yet"
    return f"The vault at {crm.vault.root} holds {parts}."


def tool_names(names=None, role="tools"):
    """The tools that these group and tool names stand for, in the order they are listed; every tool for None."""
    every = [tool for group in GROUPS.values() for tool in group]
    if names is None:
        return every
    if not names:
        raise OrbitError(f"{role}: name at least one group ({', '.join(GROUPS)}) or tool")
    if unknown := [n for n in names if n not in GROUPS and n not in every]:
        raise OrbitError(f"{role}: {unknown[0]!r} is neither a group ({', '.join(GROUPS)}) nor a tool")
    chosen = {tool for name in names for tool in GROUPS.get(name, (name,))}
    return [tool for tool in every if tool in chosen]


def build(crm, tools=None):
    """The MCP server, with these tools (see `tool_names`), or all of them."""
    tools = tool_names() if tools is None else tools
    owner = _owner(crm)
    whose = f"{owner}, the vault's owner" if owner else "the vault's owner"
    left = [t for t in tool_names() if t not in tools]
    surface = (
        f"\n\nThis connection offers only some of orbit's tools; the vault's owner left out {_listed(left)}."
        if left
        else ""
    )
    instructions = INSTRUCTIONS.format(whose=whose, owner=owner or "the owner", vault=_vault(crm)) + surface
    mcp = MCPServer("orbit", version=__version__, instructions=instructions)

    @mcp.resource(
        VAULT_RESOURCE,
        name="vault",
        description="The vault this server serves: its folder, orbit's version, and its notes by type.",
        mime_type="application/json",
    )
    async def vault_resource() -> str:  # async, as the tools: the index is used on the event loop's thread alone
        counts = {t: n for t, n in crm.index.counts().items() if t}
        return json.dumps({"vault": str(crm.vault.root), "version": __version__, "notes": counts}, ensure_ascii=False)

    @mcp.tool(annotations=READ)
    async def resolve_entity(
        type: Annotated[Literal["person", "organization", "topic"], Field(description="What to look for.")],
        names: Annotated[
            list[str] | None,
            Field(description='Names as written, in any order or form, e.g. ["Müller, Hans", "H. Müller", "Hansi"].'),
        ] = None,
        emails: Annotated[list[str] | None, Field(description="Email addresses, e.g. the sender's.")] = None,
        domain: Annotated[
            str | None, Field(description="A company's domain or web address, e.g. acme-ag.example.")
        ] = None,
        org: Annotated[str | None, Field(description="People: the organization they work for, as written.")] = None,
        job_title: Annotated[str | None, Field(description="People: their job title, as written.")] = None,
        phone: Annotated[str | None, Field(description="A phone number, written any way.")] = None,
        uid_che: Annotated[
            str | None, Field(description="Organizations: the Swiss company UID, CHE-123.456.789.")
        ] = None,
        limit: Annotated[int, Field(description="At most this many candidates.")] = 5,
    ) -> dict:
        """Candidates for a person, organization or topic, best first, each with a score from 0 to 1, the reasons it
        matched (same email address, same name in any order, alias, initials, nickname, a name that sounds alike,
        same company domain, …) and enough context to decide: org, job title, addresses, last contact. You decide
        whether one is the same; read get_entity_context of a candidate if unsure. Pairs the owner marked as different
        people come back with `distinct_from`. The owner's own addresses return Me. An organization is found by a
        subdomain of its domain too (students.school.example, school.example). `notes` explains what was not looked
        for, such as role addresses (info@…) and free-mail domains."""
        return _run(resolve.resolve, crm, type, names, emails, domain, org, job_title, phone, uid_che, limit)

    @mcp.tool(annotations=READ)
    async def get_entity_context(
        id_or_name: Ref,
        since: Annotated[
            str | None, Field(description="Only observations and interactions from this date on, YYYY-MM-DD.")
        ] = None,
    ) -> dict:
        """Everything about one note: its fields; its observations, newest first; the last change of each field, with
        date and source; its links out and the notes linking to it; its recent interactions; its open tasks; pending
        reviews about it; and its other sections, such as the owner's Notes or an interaction's Summary. For an
        interaction in a thread with others, `thread`: its interactions, oldest first, their topics and the open
        tasks they gave rise to."""
        return _run(reads.context, crm, id_or_name, since)

    @mcp.tool(annotations=READ)
    async def search_entities(
        query: Annotated[str, Field(description="Words to find: names, addresses, domains, job titles, any text.")],
        type: Annotated[
            Literal["person", "organization", "interaction", "task", "topic", "review"] | None,
            Field(description="Only notes of this type."),
        ] = None,
        limit: Annotated[int, Field(description="At most this many results.")] = 10,
    ) -> list[dict]:
        """Full-text and fuzzy search over names, aliases, addresses, domains, job titles, observations and the text
        of notes, best first. Names match without umlauts or accents too ("Mueller" finds Müller), words match by
        their beginning, and a surname that sounds alike is found when nothing else is (`matched: "sound"`). For
        deciding whether someone is already in the vault, use resolve_entity."""
        return _run(reads.search, crm, query, type, limit)

    @mcp.tool(annotations=READ)
    async def list_entities(
        type: Annotated[
            Literal["person", "organization", "interaction", "task", "topic", "review"],
            Field(description="The type of note."),
        ],
        filters: Annotated[
            dict[str, Any] | None,
            Field(
                description='Conditions on fields, all of which must hold: a value, e.g. {"org": "[[Acme AG]]"} or '
                '{"org": "Acme AG"}, which a list field meets if it holds it; a list for any of its values, e.g. '
                '{"status": ["open", "waiting"]}; {"not": value or list}; {"exists": true or false}; or comparisons, '
                'e.g. {"due": {"<": "2026-11-01"}}, which compare at the precision given, so {"<=": "2026-10"} '
                "includes all of October. Notes without the field fail comparisons."
            ),
        ] = None,
        sort: Annotated[
            str | None, Field(description='A field to sort by, with "-" first for descending, e.g. "-last_contact".')
        ] = None,
        limit: Annotated[int, Field(description="At most this many results; `total` counts them all.")] = 50,
    ) -> dict:
        """Notes of a type whose front matter meets the filters, with all their fields. For example: everyone at an
        organization; open tasks due before a date; people not contacted since a date."""
        return _run(reads.list_entities, crm, type, filters, sort, limit)

    @mcp.tool(annotations=WRITE)
    async def log_interaction(
        kind: Annotated[
            Literal["email", "meeting", "call", "message", "note", "automated"], Field(description="What it was.")
        ],
        date: Annotated[
            str, Field(description="When: an ISO 8601 time with its offset, e.g. 2026-10-14T09:32:00+02:00, or a date.")
        ],
        subject: Annotated[str | None, Field(description="An email's subject, or a short title.")] = None,
        direction: Annotated[
            Literal["inbound", "outbound"] | None, Field(description="Inbound if it came to the owner.")
        ] = None,
        sender: Annotated[
            str | None, Field(description="The person it came from (its `from`): id, name or email address.")
        ] = None,
        to: Refs = None,
        cc: Refs = None,
        participants: Annotated[list[str] | None, Field(description="Meetings and calls: the people there.")] = None,
        mentioned: Annotated[
            list[str] | None, Field(description="People it mentions; unlike the others, not counted as contact.")
        ] = None,
        orgs: Annotated[list[str] | None, Field(description="Organizations it concerns.")] = None,
        topics: Annotated[list[str] | None, Field(description="Topics it concerns.")] = None,
        language: Annotated[str | None, Field(description='Its language, e.g. "de".')] = None,
        summary: Annotated[str | None, Field(description="What it says, in a few sentences.")] = None,
        decisions: Annotated[list[str] | None, Field(description="Decisions it states, one per item.")] = None,
        key_quote: Annotated[str | None, Field(description="The sentence that matters most, word for word.")] = None,
        documents: Annotated[
            list[dict[str, str]] | None,
            Field(description='Attachments or documents it refers to: [{"title": "…", "document": URL, path or id}].'),
        ] = None,
        message_id: Annotated[
            str | None, Field(description="An email's Message-ID; logging it again returns the existing note.")
        ] = None,
        in_reply_to: Annotated[str | None, Field(description="An email's In-Reply-To.")] = None,
        references: Annotated[
            list[str] | None, Field(description="An email's References, oldest first; the first names the thread.")
        ] = None,
        source_file: Annotated[
            str | None, Field(description="Where the original is stored, e.g. the .eml file.")
        ] = None,
        sha256: Annotated[str | None, Field(description="The SHA-256 of the original file, in hex.")] = None,
    ) -> dict:
        """Create a note for an email, meeting, call or message, and return its id: the `source` for everything learnt
        from it. Give people as they appear, by name or by the addresses in an email's headers, and the organizations
        and topics it concerns: those in the vault are linked; the others are left out and listed under
        `unknown_addresses`, `unknown_people`, `unknown_orgs` and `unknown_topics` (create them with this interaction
        as source, then add them with one link_entities call and `links`), role addresses under `role_addresses`. A
        `source_file` that is a local file is linked in the note's Original section. Idempotent: a second call with
        the same `message_id`, or without one with the same kind, date, subject and sender, returns the existing note
        with `existing: true` and `recorded`: the people, organizations and topics it links, whether it has a
        summary and key quote, its decisions, tasks and documents, so that a retry adds only what is missing. People
        it was with get their `last_contact` set if it is newer. An email that answers
        one in the vault (by `in_reply_to` or `references`) links it in `replies_to`, and the answer then holds its
        `thread`: the interactions in it, their topics and the open tasks they gave rise to. Read those before
        create_task: a commitment repeated in a reply is likely one of them. `open_tasks` lists the other open tasks
        of the people and organizations it is with, up to 50 (`open_tasks_more` counts the rest): one it settles (a
        refund that came, an answer given) is update_task's to close. Tasks it gives rise to come from create_task,
        which lists them under Action items."""
        return _run(
            writes.log_interaction,
            crm,
            kind,
            date,
            subject,
            direction,
            sender,
            to,
            cc,
            participants,
            mentioned,
            orgs,
            topics,
            language,
            summary,
            decisions,
            key_quote,
            documents,
            message_id,
            in_reply_to,
            references,
            source_file,
            sha256,
        )

    @mcp.tool(annotations=WRITE)
    async def upsert_person(
        match: Match,
        fields: Annotated[
            dict[str, Any],
            Field(
                description="Person fields: name, aliases, emails, phones, org, job_title, department, former_orgs, "
                "reports_to, assistant_of, colleague_of, introduced_by, context (professional, personal, both), "
                "languages, salutation (du, Sie), location, next_followup, review_status (confirmed, needs_review). "
                'Lists are lists; links name existing notes, e.g. "org": "Acme AG".'
            ),
        ],
        source: Source,
        resolution_reason: Reason = None,
        provisional: Annotated[
            bool,
            Field(
                description="Unsure it's new: mark it needs_review, then call propose_review. Not with distinct_from."
            ),
        ] = False,
        distinct_from: Distinct = None,
    ) -> dict:
        """Create a person, or add to one. Call resolve_entity first. On an existing person, lists (emails, aliases,
        phones, languages, …) gain the new items and empty fields are filled; a field that holds a different value is
        left alone and reported under `conflicts`, since changing it is set_fields' job. Colleagues are linked both
        ways. A role address (info@…) is refused, and so is an address that belongs to someone else. A person given no
        org, with none yet, gets the organization whose domain their address is at, or under (`org_from_domain`); the
        owner never does."""
        return _run(writes.upsert_person, crm, match, fields, source, resolution_reason, provisional, distinct_from)

    @mcp.tool(annotations=WRITE)
    async def upsert_organization(
        match: Match,
        fields: Annotated[
            dict[str, Any],
            Field(
                description="Organization fields: name, aliases, domains, uid_che, industry, location, address, "
                "website, parent, relationship (client, prospect, partner, vendor, employer, personal)."
            ),
        ],
        source: Source,
        resolution_reason: Reason = None,
        distinct_from: Distinct = None,
    ) -> dict:
        """Create an organization, or add to one, as upsert_person does for people. Organizations are known by their
        domains, their Swiss UID and their name without legal form (AG, GmbH, SA, Sàrl, …): resolve_entity first.
        Free-mail domains (gmail.com, …) are refused, and so is a domain or UID that belongs to another
        organization."""
        return _run(writes.upsert_organization, crm, match, fields, source, resolution_reason, distinct_from)

    @mcp.tool(annotations=WRITE)
    async def upsert_topic(
        match: Match,
        fields: Annotated[
            dict[str, Any],
            Field(description="Topic fields: name, aliases, status (active, paused, closed), orgs, people."),
        ],
        source: Source,
        resolution_reason: Annotated[str | None, Field(description="Why it is new, to keep in its history.")] = None,
        distinct_from: Distinct = None,
    ) -> dict:
        """Create a topic (a project, a deal in progress, a recurring theme), or add to one, as upsert_person does for
        people. A new topic is active unless told otherwise; "new" with the name of an existing topic adds to that
        one."""
        return _run(writes.upsert_topic, crm, match, fields, source, resolution_reason, distinct_from)

    @mcp.tool(annotations=WRITE)
    async def link_entities(
        entity: Annotated[str, Field(description="The note whose fields are set: id or name.")],
        source: Source,
        relation: Annotated[
            str | None,
            Field(
                description="The field. Person: org, reports_to, assistant_of, colleague_of, introduced_by. "
                "Organization: parent. Interaction: from, to, cc, participants, mentioned, orgs, topics. Task: "
                "related. Topic: orgs, people."
            ),
        ] = None,
        to: Annotated[
            str | None, Field(description="The note it links to: id, name, or a person's email address.")
        ] = None,
        links: Annotated[
            list[dict[str, str]] | None,
            Field(
                description='Several links at once instead of relation and to, e.g. [{"relation": "to", "to": '
                '"Hans Müller"}, {"relation": "topics", "to": "Wartungsvertrag 2027"}].'
            ),
        ] = None,
    ) -> dict:
        """Link a note to others that exist, through its relation fields: one (`relation`, `to`), or several at once
        (`links`), every one checked before any is written. colleague_of is written on both notes. Setting a person's
        org records the change in their history and moves the old one to former_orgs. Adding a person to an
        interaction's from, to, cc or participants sets their last_contact."""
        return _run(writes.link_entities, crm, entity, relation, to, source, links)

    @mcp.tool(annotations=WRITE)
    async def link_document(
        entity: Ref,
        document: Annotated[str, Field(description="Where the document is: a URL, a file path or a document id.")],
        title: Annotated[str, Field(description="What the document is called.")],
        source: Source,
    ) -> dict:
        """Record a document outside the vault on a person, organization, interaction or topic: in its `documents`
        field and its Documents section. The same document twice is recorded once."""
        return _run(writes.link_document, crm, entity, document, title, source)

    @mcp.tool(annotations=WRITE)
    async def add_observation(
        entity: Annotated[str, Field(description="A person, organization or topic: id or name.")],
        statement: Annotated[str, Field(description="The fact, in one sentence, e.g. 'Decides on the budget'.")],
        evidence: Annotated[
            str,
            Field(description="The source's words that state it, quoted exactly; parts not together joined with …."),
        ],
        confidence: Annotated[
            Literal["high", "medium"], Field(description="high if stated outright, medium if clearly implied.")
        ],
        source: Source,
        observed_at: Annotated[
            str | None, Field(description="When it was true, YYYY-MM-DD; the source interaction's date by default.")
        ] = None,
    ) -> dict:
        """Note a fact about a person, organization or topic, with its evidence and source, as a line in its
        Observations. The same statement from the same source, or the same evidence from another (an email sent
        twice, a fact repeated in quoted history), is recorded once. Evidence not in the source interaction's file as
        written is refused, where orbit can read that file. For facts that are fields (a job title, an address), use
        upsert_* or set_fields."""
        return _run(writes.add_observation, crm, entity, statement, evidence, confidence, source, observed_at)

    @mcp.tool(annotations=WRITE)
    async def set_fields(
        entity: Annotated[str, Field(description="A person, organization or topic: id or name.")],
        changes: Annotated[
            dict[str, Any],
            Field(
                description='Single-value fields and their new values, e.g. {"job_title": "Head of Procurement"}; '
                "null clears one."
            ),
        ],
        source: Source,
        observed_at: Annotated[str, Field(description="When the source says it, YYYY-MM-DD.")],
        evidence: Annotated[
            str | None, Field(description="The source's words, kept if a change isn't applied.")
        ] = None,
        remove: Annotated[
            dict[str, list[str]] | None,
            Field(
                description='Items to take out of list fields, e.g. {"emails": ["old@acme.example"]} or '
                '{"former_orgs": ["Beta AG"]}; a colleague comes out of both notes.'
            ),
        ] = None,
    ) -> dict:
        """Change fields that hold a value already, each with a line in the note's history. A change older than the
        field's last one (its `observed_at` before that change's date) isn't applied: a new value becomes an
        observation, a clearing is dropped, and `not_applied` says so. Lists grow with upsert_* and link_entities;
        `remove` takes items out of them, also with a history line (`removed` lists what came out). A person's org
        that the same source set before is corrected, not moved to former_orgs."""
        return _run(writes.set_fields, crm, entity, changes, source, observed_at, evidence, remove)

    @mcp.tool(annotations=WRITE)
    async def create_task(
        title: Annotated[str, Field(description="What is to be done, as the task's name.")],
        owner: Annotated[
            str,
            Field(description="Who is to do it: a person, or an organization (a refund, a fix); Me for the owner."),
        ],
        origin: Annotated[str, Field(description="The interaction it comes from: id or name.")],
        status: Annotated[
            Literal["open", "waiting", "done", "cancelled"],
            Field(description="open: the owner's to do; waiting: someone promised it to the owner."),
        ] = "open",
        due: Day = None,
        due_note: Annotated[str | None, Field(description='The deadline as stated, e.g. "nächste Woche".')] = None,
        related: Refs = None,
        details: Annotated[str | None, Field(description="The commitment as stated, word for word.")] = None,
        match: Annotated[
            str | None,
            Field(
                description='Only after create_task refused similar open tasks: "new" if this is another task, or '
                "the id of the one it is."
            ),
        ] = None,
    ) -> dict:
        """Create a task: what the owner promised, what was asked of them, or what someone promised them (waiting).
        It is listed under its interaction's Action items. The same title from the same origin returns the existing
        task. An open task with a title like it, from the same thread or for the same owner and a related note, is
        refused and named, since a commitment repeated in a reply is likely that one: then pass `match`."""
        return _run(writes.create_task, crm, title, owner, origin, status, due, due_note, related, details, match)

    @mcp.tool(annotations=APPEND)
    async def update_task(
        task: Annotated[str, Field(description="The task: id or name.")],
        source: Source,
        status: Annotated[
            Literal["open", "waiting", "done", "cancelled"] | None, Field(description="Its new status.")
        ] = None,
        due: Day = None,
        due_note: Annotated[str | None, Field(description="The deadline as stated.")] = None,
        note: Annotated[str | None, Field(description="What happened, appended to its Details.")] = None,
    ) -> dict:
        """Change a task's status or due date, or add a note, each recorded in its Details with date and source."""
        return _run(writes.update_task, crm, task, source, status, due, due_note, note)

    @mcp.tool(annotations=WRITE)
    async def propose_review(
        kind: Annotated[
            Literal["duplicate", "job_change", "address", "other", "question"],
            Field(
                description="duplicate: two people, organizations or topics that may be one. address: whether an "
                "address is a person's (one candidate). job_change: whether a person works at an organization now. "
                "other: any yes/no question. question: an open one, answered in words."
            ),
        ],
        question: Annotated[
            str,
            Field(
                description="One question: for an open one, what only the owner can tell, which they answer in a "
                'sentence; else one they answer with yes or no, e.g. "Is Hans the same person as Hans Müller?".'
            ),
        ],
        candidates: Annotated[list[str], Field(description="The notes it is about; two for a duplicate.")],
        evidence_for: Annotated[list[str], Field(description="What speaks for it, one point per item.")],
        evidence_against: Annotated[list[str], Field(description="What speaks against it.")],
        source: Source,
        address: Annotated[str | None, Field(description="For an address review: the address.")] = None,
    ) -> dict:
        """Ask the owner: a review note with one question, which they answer in Obsidian by ticking Yes or No, which
        sets its `decision`. For a duplicate, yes merges them, as merge_entities does, even where they were recorded
        as different, and no records the two as different on both notes. For an address, yes adds it to the person's
        emails; for a job change of a person and an organization, yes makes it theirs. An open question the owner
        answers in its `answer` field, in words; orbit then sets its decision to `answered` (list_entities type
        review, decision answered, shows the answer), and whoever acts on it records that with settle_review. Asking
        what a review asks already (a duplicate, address or job change of the same notes; another question in the
        same words) returns that review, pending or answered, with the owner's `decision` and `answer`: their answer
        stands, so act on it rather than ask again. What the owner answered shows in get_entity_context's
        answered_reviews too."""
        return _run(reviews.propose, crm, kind, question, candidates, evidence_for, evidence_against, source, address)

    @mcp.tool(annotations=WRITE)
    async def settle_review(
        review: Annotated[str, Field(description="The review answered: id or name.")],
        done: Annotated[str, Field(description="What was done with the answer, in a line.")],
        source: Source,
    ) -> dict:
        """Record what was done with the owner's answer to a review, once: a line under its `## Applied`, and its
        `applied` date, so that no one acts on it twice. Refused while the owner hasn't answered."""
        return _run(reviews.settle, crm, review, done, source)

    @mcp.tool(annotations=DELETE)
    async def merge_entities(
        keep: Annotated[str, Field(description="The note that stays, with its name: id or name.")],
        drop: Annotated[str, Field(description="The note merged into it, then deleted: id or name.")],
        source: Source,
    ) -> dict:
        """Merge two notes about the same person, organization or topic. `keep` stays under its name and takes the
        older of the two ids; the other id is kept in `merged_from`, so it still finds the note. Lists are united,
        blank fields filled from `drop`, observations and history carried over, and `drop`'s name kept in `aliases`.
        Where the two hold different values, `keep`'s stay, and a review asks the owner whether they are right
        (`conflicts`, `review`). Every link to `drop` is rewritten to `keep`, except in notes that can't be read
        (`links_left`), and `drop` goes to the vault's .trash, from where it can be restored. Refused for notes
        recorded as different (`distinct_from`): only the owner's answer to a duplicate review merges those. Resolve
        and compare with get_entity_context first; when unsure, propose_review instead."""
        return _run(upkeep.merge, crm, keep, drop, source)

    @mcp.tool(annotations=WRITE)
    async def rename_entity(
        id_or_name: Ref,
        new_name: Annotated[str, Field(description="Its new name, which becomes its file name and link target.")],
        source: Source,
    ) -> dict:
        """Rename a note: its file, and every link to it, wherever it is, except in notes that can't be read
        (`links_left`, with the reason). A person's, organization's or topic's `name` changes with it, with a history
        line, and the old name joins `aliases`. Refused if another note has the name."""
        return _run(upkeep.rename, crm, id_or_name, new_name, source)

    @mcp.tool(annotations=WRITE)
    async def link_by_domain(
        dry_run: Annotated[bool, Field(description="Only say who would be linked.")] = False,
    ) -> dict:
        """Link every person without an organization, but the owner, to the organization their address is at: the
        one whose domains hold its domain, or the nearest domain it is under (students.school.example,
        school.example); never by a free-mail domain, nor where several organizations claim it. Each link gets a
        history line that names the address, dated by their last contact. Returns who was linked (`linked`), and the
        notes that couldn't be read (`unreadable`)."""
        return _run(upkeep.link_by_domain, crm, dry_run)

    @mcp.tool(annotations=WRITE)
    async def create_missing_references(
        dry_run: Annotated[bool, Field(description="Only say what would be done.")] = False,
    ) -> dict:
        """Give every link to a note that doesn't exist yet one. A link that names an alias of exactly one person,
        organization or topic is rewritten to link that note (`mapped`). A link in a field that leads to one type,
        such as a person's `org` or a topic's `people`, gets a stub note of that type, a person marked needs_review
        (`created`). The rest is left, with the reason (`skipped`): links only in text, whose type is unknown, and
        aliases of several notes. Links in notes that can't be read stay as they are (`links_left`)."""
        return _run(upkeep.create_missing_references, crm, dry_run)

    @mcp.tool(annotations=WRITE)
    async def lint_vault(
        fix: Annotated[
            bool, Field(description="Repair what is safe: missing ids, addresses not in lower case.")
        ] = False,
    ) -> dict:
        """Check the whole vault: schema conformance, missing or duplicate ids, the same email address on two people,
        clashing file names, links to notes that don't exist, unknown fields, and notes edited by hand that broke a
        rule. Issues are errors or warnings, each with the note, its path and what to do."""
        return _run(lint.lint, crm, fix)

    @mcp.tool(annotations=DELETE)
    async def retract_observation(
        entity: Annotated[str, Field(description="A person, organization or topic: id or name.")],
        statement: Annotated[
            str, Field(description="The observation's statement, exactly as get_entity_context shows it.")
        ],
        why: Annotated[str, Field(description="Why it isn't so, in a line, e.g. 'the email was about Anna Keller'.")],
        source: Source,
    ) -> dict:
        """Take back an observation that isn't so, or that sits on the wrong note: it leaves the note's Observations,
        and a line in its History keeps it, with its evidence and source, why, and this source. Every observation of
        the note with that statement goes (`retracted`: how many). To record the fact where it belongs,
        add_observation there."""
        return _run(writes.retract_observation, crm, entity, statement, why, source)

    for name in left:
        mcp.remove_tool(name)
    return mcp


def _listed(items):
    return ", ".join(items[:-1]) + f" and {items[-1]}" if len(items) > 1 else "".join(items)


def http_app(crm, host, tools=None):
    """The streamable HTTP app: /mcp with the tools the vault serves (see `tool_names`), /mcp/write without upkeep,
    and /mcp/read with the read tools alone, so that a client gets a narrower surface by its URL."""
    tools = tool_names() if tools is None else tools
    servers = []
    for path, groups in ENDPOINTS.items():
        mcp = build(crm, tools if groups is None else [t for t in tool_names(groups) if t in tools])
        # The host decides on each endpoint's protection against DNS rebinding.
        servers.append((mcp, mcp.streamable_http_app(streamable_http_path=path, host=host)))

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with contextlib.AsyncExitStack() as stack:
            for mcp, _ in servers:
                await stack.enter_async_context(mcp.session_manager.run())
            yield

    return Starlette(routes=[route for _, app in servers for route in app.routes], lifespan=lifespan)


def serve(root, host=None, port=None, stdio=False, tools=None):
    """Open the vault, bring its index up to date, and serve it until stopped: the tools that `tools` names (group
    and tool names), or else orbit.toml's [server] tools, or else all. The run's log goes to a file of its own."""
    path = logs.start("serve", datetime.datetime.now())
    try:
        with Crm(root) as crm:
            config = crm.vault.config
            if tools is not None:
                allowed = tool_names(tools, "--tools")
            else:
                allowed = tool_names(config.tools, f"{crm.vault.path(CONFIG)}: server.tools")
            report = crm.refresh()
            console.say(f"orbit {__version__}: {crm.vault.root}, index up to date ({report}); this run's log: {path}")
            anyio.run(_serve, crm, host or config.host, port or config.port, stdio, allowed)
    except (OrbitError, OSError) as e:
        log.error("%s", e)  # for the log; the command says it
        raise
    except KeyboardInterrupt:
        log.info("stopped")
        raise
    finally:
        logs.stop()


async def _serve(crm, host, port, stdio, tools):
    stop = anyio.Event()
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(watch.watch, crm, stop)
        try:
            if stdio:
                await build(crm, tools).run_stdio_async()
            else:
                address = f"http://[{host}]:{port}/mcp" if ":" in host else f"http://{host}:{port}/mcp"
                console.say(f"orbit MCP server on {address}")
                console.say("  /mcp/write: no upkeep (merges, renames, lint, retractions, …); /mcp/read: reading only")
                if host not in LOCAL_HOSTS:
                    console.say(
                        f"warning: listening on {host}, so anyone who reaches port {port} can read and change the "
                        "CRM: orbit has no authentication"
                    )
                await _serve_http(http_app(crm, host, tools), host, port)
        finally:
            stop.set()


async def _serve_http(app, host, port):
    import uvicorn

    config = uvicorn.Config(app, host=host, port=port, log_level="info", timeout_graceful_shutdown=SHUTDOWN_SECONDS)
    logs.attach("uvicorn", "uvicorn.access")  # configured just now, to pass nothing on
    await uvicorn.Server(config).serve()
