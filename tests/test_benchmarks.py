"""The benchmark's generated vault: notes in orbit's format that index and lint cleanly, the same for the same seed."""

import pytest

from benchmarks import generate
from orbit.crm import Crm
from orbit.lint import lint
from orbit.vault import Vault


@pytest.fixture
def small(tmp_path):
    counts = generate.generate(tmp_path / "vault", people=40, interactions=300, seed=1)
    return tmp_path / "vault", counts


def test_a_generated_vault_indexes_and_lints_cleanly(small, home):
    root, counts = small
    assert counts == {"person": 41, "organization": 8, "interaction": 300, "task": 12, "topic": 4, "review": 1}
    with Crm(root, home) as crm:
        report = crm.refresh()
        assert len(report.added) == sum(counts.values())
        assert crm.index.counts() == counts
        assert lint(crm)["issues"] == []


def test_the_same_seed_gives_the_same_vault(tmp_path):
    generate.generate(tmp_path / "a", people=10, interactions=50, seed=3)
    generate.generate(tmp_path / "b", people=10, interactions=50, seed=3)
    a = {p.relative_to(tmp_path / "a"): p.read_bytes() for p in sorted((tmp_path / "a").rglob("*.md"))}
    b = {p.relative_to(tmp_path / "b"): p.read_bytes() for p in sorted((tmp_path / "b").rglob("*.md"))}
    assert a == b


def test_people_have_unique_names_and_addresses(small):
    root, _ = small
    people = [Vault(root).note(f"01_People/{p.name}") for p in (root / "01_People").glob("*.md")]
    names = [p.name for p in people]
    emails = [e for p in people for e in p.fields["emails"]]
    assert len(names) == len(set(names)) == 41
    assert len(emails) == len(set(emails)) == 41
