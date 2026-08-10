# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The one dotted-numeric comparison in the daemon, and its answer when a side is unreadable."""

import pytest

from core.versions import compare_versions, known_to_be_below, version_at_least, version_at_most


@pytest.mark.parametrize(
    ("version", "bound", "order"),
    [
        ("0.1.10", "0.1.10", 0),
        ("1.4", "1.4.0", 0),
        ("0.1.9", "0.1.10", -1),
        ("0.1.10", "0.1.9", 1),
        ("0.2.0", "0.1.99", 1),
        ("1.4.1", "1.5", -1),
    ],
)
def test_orders_dotted_numbers_by_number_and_not_by_text(
    version: str, bound: str, order: int
) -> None:
    assert compare_versions(version, bound) == order


@pytest.mark.parametrize("unreadable", ["", "unknown", "0.1.x", "v0.1.10", "0.1.10-beta"])
def test_a_version_that_is_not_purely_numeric_compares_to_nothing(unreadable: str) -> None:
    assert compare_versions(unreadable, "0.1.10") is None
    assert compare_versions("0.1.10", unreadable) is None


def test_at_least_and_at_most_meet_at_the_bound() -> None:
    assert version_at_least("0.1.10", "0.1.10")
    assert version_at_most("0.1.10", "0.1.10")
    assert not version_at_least("0.1.9", "0.1.10")
    assert not version_at_most("0.1.11", "0.1.10")


@pytest.mark.parametrize("unreadable", ["", "unknown", "0.1.x"])
def test_an_unreadable_version_is_neither_proven_good_nor_proven_bad(unreadable: str) -> None:
    """The difference the whole pair guard rests on: `version_at_least` says it is not proven good,
    and `known_to_be_below` says it is not proven bad either, so nothing is refused over it."""
    assert not version_at_least(unreadable, "0.1.10")
    assert not known_to_be_below(unreadable, "0.1.10")


def test_known_to_be_below_only_when_both_sides_read_as_numbers() -> None:
    assert known_to_be_below("0.1.9", "0.1.10")
    assert not known_to_be_below("0.1.10", "0.1.10")
    assert not known_to_be_below("0.2.0", "0.1.10")
