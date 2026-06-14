"""Classify an expanded shell command as a service action.

A restart/start/reload verb against a core service is what `core/packages/start.py` defers into one
batch and what `core/safety/` attributes when a restart leaves the printer unhealthy. These pure
predicates live in their own module so both sides classify commands identically without importing
each other.

The concrete service names matched here (`moonraker`, `klipper`, `lmdctl`, `init.d`, `nginx`) are
the same U1 coupling that `intent.py`'s maps carry; moving both behind the adapter contract is the
follow-on (ADR-0029), not this split.
"""
import re

_SERVICE_ACTION_RE = re.compile(r"\b(?:restart|start|reload)\b")


def restarts_moonraker(expanded_cmd: str) -> bool:
    if "moonraker" not in expanded_cmd:
        return False
    return bool(_SERVICE_ACTION_RE.search(expanded_cmd))


def restarts_klipper(expanded_cmd: str) -> bool:
    if "klipper" not in expanded_cmd:
        return False
    return bool(_SERVICE_ACTION_RE.search(expanded_cmd))


def restarts_lmd(expanded_cmd: str) -> bool:
    if "lmdctl" not in expanded_cmd:
        return False
    return bool(_SERVICE_ACTION_RE.search(expanded_cmd))


def is_service_action(expanded_cmd: str) -> bool:
    """True for init-script / nginx service commands, which recover defers to one batch.

    Config-generation commands (sed, chown, cp) carry no service-action verb, so they keep
    running inline and the config exists before anything restarts.
    """
    if not _SERVICE_ACTION_RE.search(expanded_cmd):
        return False
    return "init.d" in expanded_cmd or "nginx" in expanded_cmd
