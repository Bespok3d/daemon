# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which plugin recovery puts back next: a plugin waits only for a service a plugin still waiting
can bring back, and otherwise keeps its place in the plan the app shows."""
from pathlib import Path

from core.packages.recovery.reapply import ServiceLedger
from core.packages.recovery.turn_order import next_to_recover

RFID_READER = Path("rfid-reader")
POWER_SWITCH = Path("power-tags")
CLOCK = Path("clock")
NEEDS_RFID = {"require": [{"service": "rfid"}]}
GIVES_POWER = {"provides": [{"service": "power"}]}
RFID_NEEDING_POWER = {"provides": [{"service": "rfid"}], "require": [{"service": "power"}]}


def test_a_plugin_waits_for_a_provider_still_to_come_back() -> None:
    manifests = {RFID_READER: RFID_NEEDING_POWER, POWER_SWITCH: GIVES_POWER}

    chosen = next_to_recover([RFID_READER, POWER_SWITCH], manifests,
                             ServiceLedger(set(), {"power", "rfid"}))

    assert chosen == POWER_SWITCH


def test_a_plugin_whose_only_provider_failed_keeps_its_place() -> None:
    """Nothing still waiting gives rfid, so the plugin is switched off now, in its plan place."""
    manifests = {RFID_READER: NEEDS_RFID, CLOCK: {}}

    chosen = next_to_recover([RFID_READER, CLOCK], manifests, ServiceLedger(set(), {"rfid"}))

    assert chosen == RFID_READER


def test_a_cycle_nothing_can_open_goes_in_plan_order() -> None:
    manifests = {
        RFID_READER: RFID_NEEDING_POWER,
        POWER_SWITCH: {**GIVES_POWER, **NEEDS_RFID},
    }

    chosen = next_to_recover([RFID_READER, POWER_SWITCH], manifests,
                             ServiceLedger(set(), {"power", "rfid"}))

    assert chosen == RFID_READER


def test_a_plugin_waits_for_a_provider_that_itself_waits_for_another() -> None:
    """The rfid reader comes back only once power is back, and still counts as coming."""
    manifests = {CLOCK: NEEDS_RFID, RFID_READER: RFID_NEEDING_POWER, POWER_SWITCH: GIVES_POWER}

    chosen = next_to_recover([CLOCK, RFID_READER, POWER_SWITCH], manifests,
                             ServiceLedger(set(), {"power", "rfid"}))

    assert chosen == POWER_SWITCH


def test_a_plugin_lacking_one_service_nothing_can_bring_back_does_not_wait_for_the_others() -> None:
    """Power is still coming, but rfid is not: the plugin is switched off either way, so it goes."""
    needs_rfid_and_power = {"require": [{"service": "rfid"}, {"service": "power"}]}
    manifests = {CLOCK: needs_rfid_and_power, POWER_SWITCH: GIVES_POWER}

    chosen = next_to_recover([CLOCK, POWER_SWITCH], manifests,
                             ServiceLedger(set(), {"power", "rfid"}))

    assert chosen == CLOCK


def test_plugins_that_need_nothing_go_in_plan_order() -> None:
    manifests = {CLOCK: {}, POWER_SWITCH: GIVES_POWER}

    chosen = next_to_recover([CLOCK, POWER_SWITCH], manifests, ServiceLedger(set(), {"power"}))

    assert chosen == CLOCK
