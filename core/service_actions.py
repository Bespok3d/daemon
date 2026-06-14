"""Classify an expanded shell command as a service action.

A restart/start/reload verb against a core service is what `core/packages/start_commands.py` defers
into one batch and what `core/safety/` attributes when a restart leaves the printer unhealthy. These
pure predicates live in their own module so both sides classify commands identically without
importing each other.

The verb regex and the klipper/moonraker service names are generic and stay here (the safety net and
probe layer name them too). The DEVICE tokens (a display control script, the init-script dir, the
web server) come from the jinni's `service_action_vocabulary()`, so the daemon names no device fact.
"""
import re

from jinni.contracts import ServiceActionVocabulary

_SERVICE_ACTION_RE = re.compile(r"\b(?:restart|start|reload)\b")


def restarts_moonraker(expanded_cmd: str) -> bool:
    if "moonraker" not in expanded_cmd:
        return False
    return bool(_SERVICE_ACTION_RE.search(expanded_cmd))


def restarts_klipper(expanded_cmd: str) -> bool:
    if "klipper" not in expanded_cmd:
        return False
    return bool(_SERVICE_ACTION_RE.search(expanded_cmd))


def restarts_lmd(expanded_cmd: str, vocabulary: ServiceActionVocabulary) -> bool:
    if not any(service in expanded_cmd for service in vocabulary.display_services):
        return False
    return bool(_SERVICE_ACTION_RE.search(expanded_cmd))


def is_service_action(expanded_cmd: str, vocabulary: ServiceActionVocabulary) -> bool:
    """True for a service-action verb against one of the device's service markers, which recover
    defers to one batch.

    Config-generation commands (sed, chown, cp) carry no service-action verb, so they keep
    running inline and the config exists before anything restarts.
    """
    if not _SERVICE_ACTION_RE.search(expanded_cmd):
        return False
    return any(marker in expanded_cmd for marker in vocabulary.service_markers)
