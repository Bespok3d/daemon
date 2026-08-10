# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The daemon refuses a daemon/jinni pair it can prove is bad, and says which side is behind."""

import pytest

from api.routes.refusals import refusal_detail
from core.packages.errors import IncompatiblePairError
from core.packages.pair_guard import guard_compatible_pair
from version import MIN_JINNI_VERSION


def _printer_runs_jinni(monkeypatch: pytest.MonkeyPatch, jinni_version: object) -> None:
    report = {} if jinni_version is None else {"jinni_version": jinni_version}
    monkeypatch.setattr(
        "core.packages.pair_guard.jinni_client.capabilities_report", lambda: report
    )


def test_refuses_a_jinni_older_than_this_daemon_will_drive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _printer_runs_jinni(monkeypatch, "0.1.7")

    with pytest.raises(IncompatiblePairError) as refused:
        guard_compatible_pair()

    assert refused.value.side == "jinni"
    assert refused.value.required == MIN_JINNI_VERSION
    assert refused.value.running == "0.1.7"


def test_the_refusal_names_which_side_to_update_and_to_which_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _printer_runs_jinni(monkeypatch, "0.1.7")

    with pytest.raises(IncompatiblePairError) as refused:
        guard_compatible_pair()

    body = refusal_detail(refused.value)
    assert body == {
        "error": "incompatible_pair", "side": "jinni",
        "required": MIN_JINNI_VERSION, "running": "0.1.7",
    }


def test_lets_a_jinni_at_the_floor_through(monkeypatch: pytest.MonkeyPatch) -> None:
    _printer_runs_jinni(monkeypatch, MIN_JINNI_VERSION)

    guard_compatible_pair()


def test_lets_a_newer_jinni_through_because_the_contract_has_no_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _printer_runs_jinni(monkeypatch, "9.9.9")

    guard_compatible_pair()


@pytest.mark.parametrize("unreadable", ["unknown", "", "0.1.x", None])
def test_a_jinni_that_will_not_say_its_version_is_not_a_proven_bad_pair(
    monkeypatch: pytest.MonkeyPatch, unreadable: object
) -> None:
    """A question the daemon could not ask must never take a working printer off its owner."""
    _printer_runs_jinni(monkeypatch, unreadable)

    guard_compatible_pair()
