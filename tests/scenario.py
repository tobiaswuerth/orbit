"""The example vault's story as tool calls: what an agent does, through orbit's tools alone, to build it from an empty
vault. Each step is (day, tool, arguments); arguments name notes as links write them, so the steps need no ids."""

import re

EMAIL = "[[2026-10-14 Email – AW Offerte Wartungsvertrag 2027]]"
SAILING = "[[2026-10-18 Email – Segelwochenende Bodensee]]"
ID = re.compile(r"\b(per|org|int|tsk|top|rev)_[0-9A-Z]{26}\b")

OWNER = ("Tobias", ["tobias@meinefirma.example", "tobias.privat@mail.example"])

STEPS = [
    (
        "2026-10-14",
        "log_interaction",
        {
            "kind": "email",
            "date": "2026-10-14T09:32:00+02:00",
            "subject": "AW: Offerte Wartungsvertrag 2027",
            "direction": "inbound",
            "to": ["Me"],
            "language": "de",
            "summary": "Hans confirms that the 2027 budget is approved and asks for a revised offer by 1 November, "
            "including an option for weekend on-call service. Anna Keller from Acme's engineering will handle the "
            "technical clarification and get in touch next week.",
            "decisions": ["Acme AG has approved the budget for the 2027 maintenance contract."],
            "key_quote": "Das Budget für 2027 ist freigegeben.",
            "message_id": "<20261014093200.4711@acme-ag.example>",
            "in_reply_to": "<20261010160500.0815@meinefirma.example>",
            "references": ["<20261010160500.0815@meinefirma.example>"],
            "source_file": "mail/processed/2026/2026-10-14 AW Offerte Wartungsvertrag 2027.eml",
            "sha256": "5bedd25b82fa9eb7a0b72d352acd9e390083efd9be6aa866591c6237ee117980",
        },
    ),
    (
        "2026-10-14",
        "upsert_organization",
        {
            "match": "new",
            "fields": {
                "name": "Acme AG",
                "domains": ["acme-ag.example"],
                "location": "Winterthur",
                "address": "Industriestrasse 12, 8400 Winterthur",
            },
            "source": EMAIL,
            "resolution_reason": "no candidate matched acme-ag.example",
        },
    ),
    (
        "2026-10-14",
        "upsert_person",
        {
            "match": "new",
            "fields": {
                "name": "Hans Müller",
                "emails": ["hans.mueller@acme-ag.example"],
                "phones": ["+41 52 123 45 67"],
                "org": "Acme AG",
                "job_title": "Leiter Einkauf",
                "context": "professional",
                "languages": ["de"],
                "salutation": "du",
            },
            "source": EMAIL,
            "resolution_reason": "no candidate matched hans.mueller@acme-ag.example",
        },
    ),
    (
        "2026-10-14",
        "upsert_person",
        {
            "match": "new",
            "fields": {
                "name": "Anna Keller",
                "emails": ["anna.keller@acme-ag.example"],
                "org": "[[Acme AG]]",
                "department": "Engineering",
                "colleague_of": ["Hans Müller"],
                "context": "professional",
            },
            "source": EMAIL,
            "resolution_reason": "no candidate matched anna.keller@acme-ag.example",
        },
    ),
    (
        "2026-10-14",
        "upsert_topic",
        {
            "match": "new",
            "fields": {"name": "Wartungsvertrag 2027", "orgs": ["Acme AG"], "people": ["Hans Müller", "Anna Keller"]},
            "source": EMAIL,
        },
    ),
    ("2026-10-14", "link_entities", {"entity": EMAIL, "relation": "from", "to": "Hans Müller", "source": EMAIL}),
    ("2026-10-14", "link_entities", {"entity": EMAIL, "relation": "cc", "to": "Anna Keller", "source": EMAIL}),
    ("2026-10-14", "link_entities", {"entity": EMAIL, "relation": "orgs", "to": "Acme AG", "source": EMAIL}),
    (
        "2026-10-14",
        "link_entities",
        {"entity": EMAIL, "relation": "topics", "to": "Wartungsvertrag 2027", "source": EMAIL},
    ),
    (
        "2026-10-14",
        "add_observation",
        {
            "entity": "Hans Müller",
            "statement": "On first-name terms with Tobias (du)",
            "evidence": "Lieber Tobias",
            "confidence": "high",
            "source": EMAIL,
        },
    ),
    (
        "2026-10-14",
        "add_observation",
        {
            "entity": "Hans Müller",
            "statement": "Decides on the budget for the 2027 maintenance contract",
            "evidence": "Das Budget für 2027 ist freigegeben.",
            "confidence": "medium",
            "source": EMAIL,
        },
    ),
    (
        "2026-10-14",
        "add_observation",
        {
            "entity": "Anna Keller",
            "statement": "Handles the technical clarification for the 2027 maintenance contract",
            "evidence": "Anna Keller aus unserem Engineering übernimmt die technische Abklärung",
            "confidence": "high",
            "source": EMAIL,
        },
    ),
    (
        "2026-10-14",
        "add_observation",
        {
            "entity": "Wartungsvertrag 2027",
            "statement": "Acme AG approved the budget for 2027",
            "evidence": "Das Budget für 2027 ist freigegeben.",
            "confidence": "high",
            "source": EMAIL,
        },
    ),
    (
        "2026-10-14",
        "create_task",
        {
            "title": "Send revised offer for Wartungsvertrag 2027",
            "status": "open",
            "due": "2026-11-01",
            "due_note": "bis am 1. November",
            "owner": "Me",
            "related": ["Hans Müller", "Acme AG", "Wartungsvertrag 2027"],
            "origin": EMAIL,
            "details": "Wir bräuchten die revidierte Offerte bis am 1. November, inkl. der Option für den "
            "Pikettdienst am Wochenende.",
        },
    ),
    (
        "2026-10-14",
        "create_task",
        {
            "title": "Anna Keller to follow up on the technical clarification",
            "status": "waiting",
            "due": "2026-10-23",
            "due_note": "nächste Woche",
            "owner": "Anna Keller",
            "related": ["Acme AG", "Wartungsvertrag 2027"],
            "origin": EMAIL,
            "details": "Anna Keller aus unserem Engineering übernimmt die technische Abklärung und meldet sich nächste "
            "Woche bei dir.",
        },
    ),
    (
        "2026-10-18",
        "log_interaction",
        {
            "kind": "email",
            "date": "2026-10-18T19:02:00+02:00",
            "subject": "Segelwochenende Bodensee",
            "direction": "inbound",
            "to": ["Me"],
            "language": "de",
            "summary": "Hans asks whether Tobias has time to go sailing on Lake Constance on 7 November, starting in "
            "Romanshorn.",
            "key_quote": "Hast du am 7. November Zeit fürs Segeln auf dem Bodensee?",
            "message_id": "<CAF3x9Q2kq7Lm@mail.gmail.com>",
            "source_file": "mail/processed/2026/2026-10-18 Segelwochenende Bodensee.eml",
            "sha256": "e26c3227854f387aa64071c79afc02fc72b779c7613d5526ec57744d80688fd1",
        },
    ),
    (
        "2026-10-18",
        "upsert_person",
        {
            "match": "new",
            "fields": {
                "name": "Hans",
                "aliases": ["Hansi"],
                "emails": ["hansi.mueller@gmail.com"],
                "context": "personal",
                "salutation": "du",
            },
            "source": SAILING,
            "resolution_reason": "provisional, possibly [[Hans Müller]], see [[2026-10-18 Duplicate – Hans and Hans "
            "Müller]]",
            "provisional": True,
        },
    ),
    ("2026-10-18", "link_entities", {"entity": SAILING, "relation": "from", "to": "Hans", "source": SAILING}),
    (
        "2026-10-18",
        "propose_review",
        {
            "kind": "duplicate",
            "question": "Is Hans <hansi.mueller@gmail.com> the same person as Hans Müller of Acme AG?",
            "candidates": ["Hans", "Hans Müller"],
            "evidence_for": [
                "The address hansi.mueller@gmail.com carries the surname Müller (as mueller), and Hansi is a "
                "nickname for Hans.",
                "Both write to Tobias on first-name terms (du).",
            ],
            "evidence_against": [
                "A private address and a private topic. Nothing in the email mentions Acme AG.",
                'Signed only "Hansi", with no surname and no signature.',
            ],
            "source": SAILING,
        },
    ),
]


def without_ids(text):
    return ID.sub(lambda m: f"{m[1]}_ID", text)
