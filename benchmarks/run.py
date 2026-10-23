"""Measure orbit on a generated vault: building the index, starting up, and each tool, as an agent calls them.

    uv run python -m benchmarks.run --people 5000 --interactions 50000

Prints a Markdown table: the median and 95th percentile of each tool's time, over `--rounds` calls with varied
arguments. Runs in a temporary folder (or one under `--dir`), which it removes.
"""

import argparse
import json
import platform
import random
import shutil
import statistics
import tempfile
import time
from pathlib import Path

from orbit import __version__, lint, reads, resolve, upkeep, writes
from orbit.crm import Crm

from . import generate


def timed(fn, *args, **kwargs):
    start = time.perf_counter()
    fn(*args, **kwargs)
    return time.perf_counter() - start


def measure(people, interactions, rounds, seed=0, where=None):
    rng = random.Random(seed)
    folder = Path(tempfile.mkdtemp(prefix="orbit-bench-", dir=where))
    try:
        root, home = folder / "vault", folder / "home"
        start = time.perf_counter()
        counts = generate.generate(root, people, interactions, seed)
        rows = [("generate the vault", time.perf_counter() - start, None)]
        # New files can be slow to read once, for reasons outside orbit; measure orbit apart from that.
        rows.append(
            ("read every file once, without orbit", timed(lambda: [p.read_bytes() for p in root.rglob("*.md")]), None)
        )
        with Crm(root, home) as crm:
            rows.append(("build the index (first start)", timed(crm.refresh), None))
        with Crm(root, home) as crm:
            rows.append(("start with the index up to date", timed(crm.refresh), None))
            rows.append(("rebuild the index (`orbit reindex`)", timed(crm.index.rebuild), None))
            size = crm.index.path.stat().st_size
            persons = [crm.entity(r["path"]) for r in crm.index.rows("person") if r["name"] != "Me"]
            orgs = [r["name"] for r in crm.index.rows("organization")]
            emails = [r["path"] for r in crm.index.rows("interaction")]
            sample = lambda: rng.choice(persons)  # noqa: E731

            def written_as(entity):
                first, last = entity.fields["name"].split(" ", 1)
                return rng.choice([f"{last}, {first}", f"{first[0]}. {last}", entity.fields["name"].upper()])

            calls = {
                "resolve_entity, by name": lambda: resolve.resolve(crm, "person", [written_as(sample())]),
                "resolve_entity, by address": lambda: resolve.resolve(crm, "person", emails=sample().fields["emails"]),
                "search_entities": lambda: reads.search(crm, sample().fields["name"].split()[-1]),
                "get_entity_context, a person": lambda: reads.context(crm, sample().id),
                "list_entities, people at an organization": lambda: reads.list_entities(
                    crm, "person", {"org": rng.choice(orgs)}
                ),
                "list_entities, open tasks due before a date": lambda: reads.list_entities(
                    crm, "task", {"status": "open", "due": {"<": "2024-01-01"}}, sort="due"
                ),
                "list_entities, a person's interactions": lambda: reads.list_entities(
                    crm, "interaction", {"from": sample().link}
                ),
                "log_interaction": lambda: writes.log_interaction(
                    crm, "email", "2026-10-22T10:00:00+02:00", subject=f"Bench {rng.random()}", sender=sample().link
                ),
                "upsert_person, adding to an existing one": lambda: writes.upsert_person(
                    crm, sample().id, {"aliases": [f"Alias {rng.random()}"]}, "benchmark"
                ),
                "add_observation": lambda: writes.add_observation(
                    crm, sample().id, f"Fact {rng.random()}", "words", "high", "benchmark"
                ),
                "get_entity_context, an interaction": lambda: reads.context(crm, crm.entity(rng.choice(emails)).id),
            }
            for name, call in calls.items():
                times = [timed(call) for _ in range(rounds)]
                rows.append((name, statistics.median(times), sorted(times)[int(0.95 * (rounds - 1))]))
            rows.append(("lint_vault, the whole vault", timed(lint.lint, crm), None))
            rows.append(
                ("create_missing_references, a dry run", timed(upkeep.create_missing_references, crm, True), None)
            )
        return counts, rows, size
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def table(counts, rows, size, rounds):
    notes = sum(counts.values())
    lines = [
        f"orbit {__version__}, Python {platform.python_version()}, {platform.system()} {platform.release()}, "
        f"{platform.processor() or platform.machine()}",
        "",
        f"A vault of {notes:,} notes: "
        + ", ".join(f"{n:,} {t}" for t, n in counts.items())
        + f"; index {size / 2**20:.0f} MB.",
        "",
        f"| What | Median | 95th percentile (of {rounds}) |",
        "|---|---:|---:|",
    ]
    for name, median, p95 in rows:
        lines.append(f"| {name} | {_ms(median)} | {_ms(p95) if p95 is not None else ''} |")
    return "\n".join(lines)


def _ms(seconds):
    return f"{seconds:.1f} s" if seconds >= 1 else f"{seconds * 1000:.1f} ms"


def main(argv=None):
    p = argparse.ArgumentParser(description="Measure orbit on a generated vault.")
    p.add_argument("--people", type=int, default=5000)
    p.add_argument("--interactions", type=int, default=50000)
    p.add_argument("--rounds", type=int, default=50)
    p.add_argument("--json", action="store_true", help="the raw times as JSON")
    p.add_argument(
        "--dir",
        help="where to generate the vault (default: the temporary folder, where the first reading of each new file "
        "can be ten times slower)",
    )
    args = p.parse_args(argv)
    counts, rows, size = measure(args.people, args.interactions, args.rounds, where=args.dir)
    print(
        json.dumps({"counts": counts, "rows": rows, "size": size})
        if args.json
        else table(counts, rows, size, args.rounds)
    )


if __name__ == "__main__":
    main()
