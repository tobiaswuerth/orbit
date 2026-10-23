# Benchmarks

How long orbit takes on a vault of the size the brief set as its goal: 5,000 people and 50,000 interactions.

## Results

A generated vault of 58,551 notes: 5,001 people, 1,000 organizations, 50,000 email interactions over six years,
2,000 tasks, 500 topics and 50 pending reviews. The index is 167 MB. Measured with orbit 0.1.0 and Python 3.14 on
Windows 11, an Intel Core i9-14900K and an NVMe SSD; tool times are the median and 95th percentile of 50 calls with
varied arguments.

| What | Median | 95th percentile |
|---|---:|---:|
| Build the index (first start, or after deleting it) | 14.0 s | |
| Start with the index up to date | 0.9 s | |
| Rebuild the index (`orbit reindex`) | 16.1 s | |
| `resolve_entity`, by name ("Müller, Hans", "H. Müller", …) | 2.8 ms | 4.5 ms |
| `resolve_entity`, by address | 3.1 ms | 3.7 ms |
| `search_entities` | 3.3 ms | 3.8 ms |
| `get_entity_context`, a person | 0.4 ms | 0.7 ms |
| `get_entity_context`, an interaction | 0.2 ms | 0.3 ms |
| `list_entities`, people at an organization | 0.3 ms | 0.5 ms |
| `list_entities`, a person's interactions | 0.2 ms | 0.3 ms |
| `list_entities`, open tasks due before a date | 14.9 ms | 18.5 ms |
| `log_interaction` | 5.7 ms | 18.2 ms |
| `upsert_person`, adding to an existing one | 2.8 ms | 4.3 ms |
| `add_observation` | 4.5 ms | 21.8 ms |
| `lint_vault`, the whole vault | 2.3 s | |
| `create_missing_references`, a dry run | 88 ms | |

- **Building the index** reads, parses and indexes about 4,200 notes a second. It happens once: afterwards orbit
  starts by comparing each file's modification time and size with the index, and reads only what changed.
- **Tools** answer in milliseconds, writes included: a write reads its note again, writes it atomically and updates the
  index before it returns. `list_entities` filters on links through the index, and on other fields by reading the
  front matter of each note of the type, so a filter over 50,000 interactions without a link in it takes tens of
  milliseconds.
- **New files read slowly once.** Reading the 58,551 freshly generated files once, without orbit, took 20.6 s on
  this machine, while reading them a second time takes a fraction of a second; in the user's temporary folder on C:,
  the first read takes about ten times as long again. The cause lies outside orbit and wasn't pinned down: Windows
  Defender used no CPU time during those reads. A vault whose notes have been opened before, as Obsidian opens them,
  doesn't pay this; the benchmark reads every file once first, and reports that apart.

## Running it

```bash
uv run python -m benchmarks.run --people 5000 --interactions 50000 --dir /path/on/a/fast/disk
```

`benchmarks/generate.py` writes the vault, in orbit's format, the same for the same `--seed`; `benchmarks/run.py`
measures it, in a temporary folder it removes afterwards, and prints the table above. `--rounds` sets the number of
calls per tool, `--json` prints the raw times. The tests check that a generated vault indexes and lints cleanly.
