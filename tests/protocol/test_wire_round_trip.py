# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the jinni sends is what the daemon reads back, for every verb that carries a typed shape.

The jinni ships as a separate process, so every one of these shapes is flattened to JSON on the way
out and rebuilt on the way in. The safety net judges on the rebuilt values: if a field is dropped or
comes back a different type, the daemon acts on a health verdict that is not the one the printer
gave, which is the one failure that must never be silent. Each case below sends a shape with every
field filled and a value that would survive a sloppy decoder only by accident.

A reply missing a field the shape requires must arrive as a refusal, never as a raw decoder error
escaping into the daemon.
"""
import pytest

from protocol.contracts import (
    ActionResult,
    CommandEffect,
    DeviceHealth,
    FailureSignals,
    OomReport,
    ServiceHealth,
)
from protocol.wire import ProtocolError, parse_result, result_bytes

_A_DOWN_SERVICE = ServiceHealth(ready=False, detail="exited on start",
                                failed_components=("power",), warnings=("slow start",))
_A_HEALTH_REPORT = DeviceHealth(
    services={"moonraker": _A_DOWN_SERVICE},
    diagnosis="stock_service_down",
    signals=FailureSignals(sections=("[mqtt]",), modules=("paho",), files=("main.cfg",),
                           log_tails="the tail the user is shown"),
)

_ROUND_TRIPS = [
    ("health", _A_HEALTH_REPORT),
    ("classify_commands", [CommandEffect(deferrable=True, restarts_services=("klipper",),
                                         blocking_token="printing")]),
    ("run_actions", [ActionResult(ok=False, output="no such file")]),
    ("wire", [ActionResult(ok=True, output="")]),
    ("unwire", [ActionResult(ok=True, output="")]),
    ("write_files", [ActionResult(ok=True, output="wrote 2 files")]),
    ("blocked_actions", frozenset({"restart klipper", "restart moonraker"})),
    ("capability_flags", {"camera", "rfid"}),
    ("oom_report", OomReport(kills=3, token="out_of_memory", detail="the board ran out of memory")),
]


@pytest.mark.parametrize("verb,sent", _ROUND_TRIPS, ids=[verb for verb, _ in _ROUND_TRIPS])
def test_what_the_jinni_sends_is_what_the_daemon_reads_back(verb: str, sent: object) -> None:
    assert parse_result(verb, result_bytes(sent)) == sent


def test_a_health_report_keeps_the_failed_components_the_printer_named() -> None:
    """Moonraker can answer while a component of it is dead, and the safety net judges on exactly
    that, so these must not be flattened away in transit."""
    read_back = parse_result("health", result_bytes(_A_HEALTH_REPORT))

    assert read_back.services["moonraker"].failed_components == ("power",)
    assert read_back.signals.log_tails == "the tail the user is shown"
    assert read_back.diagnosis == "stock_service_down"


_REPLIES_MISSING_A_FIELD = [
    ("health", {"services": {"klipper": {"ready": True}}, "diagnosis": ""}),
    ("health", {"diagnosis": ""}),
    ("classify_commands", [{"deferrable": True}]),
    ("run_actions", [{"ok": True}]),
    ("oom_report", {"kills": 1}),
    ("health", "not a report at all"),
    ("run_actions", {"ok": True, "output": ""}),
]


@pytest.mark.parametrize("verb,half_a_reply", _REPLIES_MISSING_A_FIELD)
def test_a_reply_that_is_not_the_agreed_shape_is_refused_by_name(
    verb: str, half_a_reply: object,
) -> None:
    with pytest.raises(ProtocolError, match="does not match its contract"):
        parse_result(verb, result_bytes(half_a_reply))
