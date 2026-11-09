# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The file in a plugin's directory that says the plugin is switched off, and why: its files are
kept and nothing of it is wired or patched on the printer. A leaf, so the patch hand-over can read
it without importing the deactivation that itself hands patched files over.

The reason tells who switched the plugin off, so recovery can tell a plugin the safety net took off
from one a person switched off. The net's own reasons start with `AUTO_DEACTIVATED_PREFIX`, and a
plugin the net took off with the plugin it needs names that provider (`stranded_reason`). A plugin
the net switches off during a recovery, and one a person switched off with the plugin it needs,
carry reasons recovery does not put back.
"""

import json
from pathlib import Path

DEACTIVATED_MARKER = "deactivated.json"
AUTO_DEACTIVATED_PREFIX = "auto-deactivated: "
_DURING_A_RECOVERY = "auto-deactivated during a recovery: "
_STRANDED_START = "deactivated with "
_STRANDED_ON_REQUEST_START = "deactivated on request with "
_STRANDED_END = ", the plugin it needs"


def safety_net_reason(signal: str, during_a_recovery: bool) -> str:
    """Why the safety net switched a plugin off. A recovery has linked every plugin again, so one
    the net switches off during a recovery really fails, and the next recovery leaves it off."""
    start = _DURING_A_RECOVERY if during_a_recovery else AUTO_DEACTIVATED_PREFIX
    return f"{start}{signal}"


def stranded_reason(provider_id: str) -> str:
    """The safety net took this plugin off with `provider_id`: recovery puts both back."""
    return f"{_STRANDED_START}{provider_id}{_STRANDED_END}"


def stranded_on_request_reason(provider_id: str) -> str:
    """A person switched `provider_id` off and this plugin with it: both stay off."""
    return f"{_STRANDED_ON_REQUEST_START}{provider_id}{_STRANDED_END}"


def provider_that_stranded(reason: str) -> str | None:
    """The plugin whose switch-off took this one with it, or None when the reason names none. A note
    appended after the reason (the dropped saved files) does not hide the provider."""
    if not reason.startswith(_STRANDED_START):
        return None
    provider_id, end, _note = reason.removeprefix(_STRANDED_START).partition(_STRANDED_END)
    return provider_id if end else None


def switched_off_reason(plugin_dir: Path) -> str | None:
    """Why the plugin was switched off, or None when it is on or its marker cannot be read."""
    try:
        marker = json.loads((plugin_dir / DEACTIVATED_MARKER).read_text())
    except (OSError, ValueError):
        return None
    reason = marker.get("reason") if isinstance(marker, dict) else None
    return reason if isinstance(reason, str) else None
