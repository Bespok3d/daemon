"""Per-verb result decoders: rebuild the typed contract shape from a reply's JSON form (strict
output at the boundary).

A verb absent from the table returns its JSON-native value (str / bool / dict / None) unchanged.
Kept apart from the wire framing so the codec module stays about transport, not about which shape
each verb carries.
"""
from collections.abc import Callable
from typing import Any

from .contracts import (
    ActionResult,
    CommandEffect,
    DeviceHealth,
    FailureSignals,
    OomReport,
    ServiceHealth,
)


def _service_health(payload: dict) -> ServiceHealth:
    return ServiceHealth(
        ready=payload["ready"], detail=payload["detail"],
        failed_components=tuple(payload["failed_components"]),
        warnings=tuple(payload["warnings"]),
    )


def _failure_signals(payload: dict) -> FailureSignals:
    return FailureSignals(
        sections=tuple(payload.get("sections", [])),
        modules=tuple(payload.get("modules", [])),
        files=tuple(payload.get("files", [])),
        log_tails=payload.get("log_tails", ""),
    )


def _device_health(payload: dict) -> DeviceHealth:
    services = {name: _service_health(value) for name, value in payload["services"].items()}
    return DeviceHealth(
        services=services,
        diagnosis=payload["diagnosis"],
        signals=_failure_signals(payload.get("signals", {})),
    )


def _command_effect(payload: dict) -> CommandEffect:
    return CommandEffect(
        deferrable=payload["deferrable"],
        restarts_services=tuple(payload["restarts_services"]),
        blocking_token=payload["blocking_token"],
    )


def _action_result(payload: dict) -> ActionResult:
    return ActionResult(ok=payload["ok"], output=payload["output"])


def _oom_report(payload: dict) -> OomReport:
    return OomReport(kills=payload["kills"], token=payload["token"], detail=payload["detail"])


# The actuation verbs all answer with one ActionResult per item the daemon sent (a command, a wired
# link), in order; the daemon pairs each back to its input to build the phase log.
def _action_results(payload: Any) -> list[ActionResult]:
    return [_action_result(result) for result in payload]


_DECODERS: dict[str, Callable[[Any], Any]] = {
    "health": _device_health,
    "classify_commands": lambda payload: [_command_effect(effect) for effect in payload],
    "run_actions": _action_results,
    "wire": _action_results,
    "unwire": _action_results,
    "write_files": _action_results,
    "blocked_actions": frozenset,
    "capability_flags": set,
    "oom_report": _oom_report,
}


def decode_result(verb: str, payload: Any) -> Any:
    decoder = _DECODERS.get(verb)
    return decoder(payload) if decoder else payload
