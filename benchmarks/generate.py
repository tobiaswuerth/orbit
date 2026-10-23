"""A generated vault for measuring orbit: people at organizations, emails between them and the owner, tasks, topics
and reviews, written in orbit's format. The same seed gives the same vault.

    uv run python -m benchmarks.generate ~/bench-vault --people 5000 --interactions 50000
"""

import argparse
import datetime
import random
from pathlib import Path

from orbit import frontmatter, ids, schema, vault
from orbit.entries import Change, Observation
from orbit.names import file_name, fold
from orbit.sections import build

FIRST = """Andrea Andreas Anna Barbara Beat Bruno Carla Christian Claudia Daniel Daniela Dominik Elena Elias Eva Fabian
Franziska Gabriel Hans Heidi Irene Jakob Jana Jonas Julia Karin Katrin Lars Laura Lea Leon Lukas Manuel Marco Maria
Markus Martin Michael Monika Nadine Nicole Nina Noah Oliver Patrick Peter Petra Philipp Regula Reto Roger Ruth Sabine
Samuel Sandra Sara Silvia Simon Sonja Stefan Stefanie Susanne Thomas Tobias Ueli Urs Ursula Verena Walter Yvonne
""".split()
LAST = """Ammann Bachmann Baumann Baumgartner Berger Bieri Blaser Bolliger Brunner Bucher Burkhalter Egli Fankhauser
Fischer Frei Frey Fuchs Gerber Graf Gut Hofer Hofmann Huber Hug Imhof Iseli Jäggi Kaufmann Keller Kern Kessler Koch Kunz
Kuhn Lehmann Lüthi Marti Meier Meyer Moser Müller Nussbaum Ott Pfister Roth Rüegg Schär Schmid Schneider Schnyder
Schwarz Senn Siegenthaler Sommer Stalder Steiner Stucki Suter Tanner Vogel Vogt Wagner Walker Weber Wenger Widmer Wyss
Zaugg Zbinden Zimmermann Zürcher Brändli Gasser Hess Jenni Kälin Lang Lustenberger Mäder Nyffeler Ochsner Probst
Rindlisbacher Schaller Scheidegger Sutter Trachsel Ulrich Wäfler Wittwer Wüthrich Zeller Zingg
""".split()
WORDS = """Alpen Berg Blau Brücke Delta Falke Feld Fluss Garten Gipfel Glas Gold Hafen Holz Insel Kraft Licht Linde
Mühle Nord Quelle Rhein Ring Sonne Stahl Stern Tal Turm Wald Weide
""".split()
FORMS = ["AG", "GmbH", "SA", "Sàrl", "Genossenschaft"]
INDUSTRIES = ["Machines", "Software", "Logistics", "Food", "Construction", "Consulting", "Energy", "Health"]
CITIES = ["Zürich", "Bern", "Basel", "Winterthur", "Luzern", "St. Gallen", "Aarau", "Thun", "Chur", "Zug"]
TITLES = ["Leiter Einkauf", "CEO", "CFO", "Projektleiterin", "Engineer", "Head of Sales", "Assistentin", "CTO"]
SUBJECTS = ["Offerte", "Rechnung", "Termin", "Projekt", "Wartung", "Lieferung", "Vertrag", "Kickoff", "Anfrage"]
START = datetime.datetime(2020, 1, 1, 8, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=1)))
DAYS = 6 * 365


def generate(root, people=5000, interactions=50000, seed=0):
    """Write a vault to `root`; the number of notes of each type."""
    rng = random.Random(seed)
    root = Path(root)
    me_fields = {"id": ids.new("per", START, rng.randbytes(10)), "name": "Tobias", "me": True}
    me_fields |= {"emails": ["tobias@meinefirma.example"], "created": START.date().isoformat()}
    (root / "01_People").mkdir(parents=True, exist_ok=True)
    text = frontmatter.render(
        {"type": "person"} | me_fields | {"updated": me_fields["created"]}, build([("Notes", [])])
    )
    (root / vault.ME).write_bytes(text.encode("utf-8"))  # before init, which takes its id: the same for the same seed
    vault.init(root, "Tobias", now=START)
    me = schema.link("Me")
    written = dict.fromkeys(schema.TYPES, 0)

    def new_id(prefix, when):
        return ids.new(prefix, when, rng.randbytes(10))

    def write(type_name, path, fields, sections):
        fields = {"type": type_name} | fields
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        text = frontmatter.render(schema.order(type_name, fields), build(sections))
        (root / path).write_bytes(text.encode("utf-8"))
        written[type_name] += 1

    orgs = []
    for _ in range(max(1, people // 5)):
        name = f"{rng.choice(WORDS)} {rng.choice(WORDS)} {rng.choice(FORMS)}"
        while name in {o["name"] for o in orgs}:
            name = f"{rng.choice(WORDS)} {rng.choice(WORDS)} {rng.choice(FORMS)}"
        slug = "-".join(fold(name).split()[:2])
        orgs.append({"name": name, "domain": f"{slug}-{len(orgs)}.example", "city": rng.choice(CITIES)})
    names = set()
    while len(names) < people:
        names.add((rng.choice(FIRST), rng.choice(LAST)))
    persons = []
    for first, last in sorted(names):
        org = rng.choice(orgs)
        local = fold(f"{first}.{last}")
        persons.append({"name": f"{first} {last}", "org": org, "email": f"{local}@{org['domain']}", "seen": None})
    days = sorted(rng.randrange(DAYS) for _ in range(interactions))
    stems, interaction_names = set(), []
    for n, day in enumerate(days):
        when = START + datetime.timedelta(days=day, minutes=rng.randrange(600))
        person = rng.choice(persons)
        inbound = rng.random() < 0.6
        subject = f"{rng.choice(SUBJECTS)} {rng.choice(WORDS)} {n}"
        stem = file_name(f"{when.date()} Email – {subject}")
        stems.add(stem)
        interaction_names.append((stem, person, when))
        person["seen"] = when.date().isoformat()
        fields = {
            "id": new_id("int", when),
            "kind": "email",
            "date": when.isoformat(timespec="seconds"),
            "direction": "inbound" if inbound else "outbound",
            "subject": subject,
            "from": schema.link(person["name"]) if inbound else me,
            "to": [me] if inbound else [schema.link(person["name"])],
            "orgs": [schema.link(person["org"]["name"])],
            "language": "de",
            "message_id": f"<{n}.{seed}@{person['org']['domain']}>",
            "created": when.date().isoformat(),
        }
        summary = [f"{person['name']} writes about {subject.lower()}."]
        folder = f"03_Interactions/{when.year}/{when.strftime('%Y-%m')}"
        write("interaction", f"{folder}/{stem}.md", fields, [("Summary", summary)])
    for org in orgs:
        when = START + datetime.timedelta(days=rng.randrange(30))
        fields = {
            "id": new_id("org", when),
            "name": org["name"],
            "domains": [org["domain"]],
            "industry": rng.choice(INDUSTRIES),
            "location": org["city"],
            "created": when.date().isoformat(),
            "updated": when.date().isoformat(),
        }
        history = [Change(when.date().isoformat(), "created", None, "generated", "benchmark").line()]
        write(
            "organization",
            f"02_Organizations/{file_name(org['name'])}.md",
            fields,
            [("Notes", []), ("History", history)],
        )
    for person in persons:
        when = START + datetime.timedelta(days=rng.randrange(30))
        fields = {
            "id": new_id("per", when),
            "name": person["name"],
            "emails": [person["email"]],
            "org": schema.link(person["org"]["name"]),
            "job_title": rng.choice(TITLES),
            "context": "professional",
            "last_contact": person["seen"],
            "review_status": "confirmed",
            "created": when.date().isoformat(),
            "updated": when.date().isoformat(),
        }
        mine = [i for i in interaction_names[:200] if i[1] is person][:2]
        observations = [
            Observation(w.date().isoformat(), "Prefers email", "per Mail bitte", schema.link(s), "medium").line()
            for s, _, w in mine
        ]
        history = [Change(when.date().isoformat(), "created", None, "generated", "benchmark").line()]
        sections = [("Notes", [])] + ([("Observations", observations)] if observations else []) + [("History", history)]
        write("person", f"01_People/{file_name(person['name'])}.md", {k: v for k, v in fields.items() if v}, sections)
    for n in range(interactions // 25):
        stem, person, when = rng.choice(interaction_names)
        fields = {
            "id": new_id("tsk", when),
            "status": rng.choice(["open", "open", "waiting", "done"]),
            "due": (when + datetime.timedelta(days=14)).date().isoformat(),
            "owner": rng.choice([me, schema.link(person["name"])]),
            "related": [schema.link(person["name"]), schema.link(person["org"]["name"])],
            "origin": schema.link(stem),
            "created": when.date().isoformat(),
            "updated": when.date().isoformat(),
        }
        write("task", f"04_Tasks/Follow up {stem} {n}.md", fields, [("Details", []), ("Notes", [])])
    for n in range(max(1, people // 10)):
        org = rng.choice(orgs)
        staff = [p for p in persons if p["org"] is org][:3]
        fields = {
            "id": new_id("top", START),
            "name": f"Projekt {org['name']} {n}",
            "status": "active",
            "orgs": [schema.link(org["name"])],
            "people": [schema.link(p["name"]) for p in staff],
            "created": START.date().isoformat(),
            "updated": START.date().isoformat(),
        }
        write(
            "topic",
            f"05_Topics/{file_name(fields['name'])}.md",
            {k: v for k, v in fields.items() if v},
            [("Notes", [])],
        )
    for n in range(max(1, people // 100)):
        a, b = rng.sample(persons, 2)
        fields = {
            "id": new_id("rev", START),
            "kind": "duplicate",
            "question": f"Is {a['name']} the same person as {b['name']}?",
            "candidates": [schema.link(a["name"]), schema.link(b["name"])],
            "decision": "pending",
            "source": "benchmark",
            "created": START.date().isoformat(),
        }
        title = file_name(f"{START.date()} Duplicate – {a['name']} and {b['name']} {n}")
        write("review", f"90_Review/{title}.md", fields, [("Evidence for", []), ("Evidence against", [])])
    written["person"] += 1  # Me.md, from orbit init
    return written


def main(argv=None):
    p = argparse.ArgumentParser(description="Generate a vault for measuring orbit.")
    p.add_argument("vault", type=Path)
    p.add_argument("--people", type=int, default=5000)
    p.add_argument("--interactions", type=int, default=50000)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args(argv)
    print(generate(args.vault, args.people, args.interactions, args.seed))


if __name__ == "__main__":
    main()
