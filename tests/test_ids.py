"""Note ids: a type prefix and a ULID."""

import datetime

import pytest

from orbit import ids


def test_new_ids_are_ulids_with_a_prefix():
    when = datetime.datetime(2026, 10, 14, 7, 40, tzinfo=datetime.UTC)
    made = ids.new("per", when, randomness=bytes(10))
    assert made == "per_01M4WNN540" + "0" * 16
    assert ids.is_valid(made, "per")
    assert ids.timestamp(made) == when
    assert ids.timestamp("per_01M4WNN540CGMAHYXV1R90AA5V") == when  # Hans Müller in the example vault


def test_ids_made_later_sort_later():
    early = ids.new("per", datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC))
    late = ids.new("per", datetime.datetime(2026, 1, 2, tzinfo=datetime.UTC))
    assert early < late


def test_random_part_differs():
    when = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    assert ids.new("tsk", when) != ids.new("tsk", when)


@pytest.mark.parametrize(
    "value, prefix, valid",
    [
        ("per_01M3V0RPR04X2CSM8CEMSVTWVA", "per", True),
        ("per_01M3V0RPR04X2CSM8CEMSVTWVA", None, True),
        ("per_01M3V0RPR04X2CSM8CEMSVTWVA", "org", False),
        ("per_01m3v0rpr04x2csm8cemsvtwva", "per", False),  # orbit writes them in capitals
        ("per_01M3V0RPR04X2CSM8CEMSVTWV", "per", False),
        ("per_81M3V0RPR04X2CSM8CEMSVTWVA", "per", False),  # beyond the year 10889
        ("per_01M3V0RPR04X2CSM8CEMSVTWVI", "per", False),  # I is not in Crockford's alphabet
        ("01M3V0RPR04X2CSM8CEMSVTWVA", None, False),
        (None, None, False),
    ],
)
def test_validation(value, prefix, valid):
    assert ids.is_valid(value, prefix) is valid
