# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The switched-off plugins recovery puts back on, besides the ones that are on.

A firmware update wipes files the plugins link into the printer, so the safety net can switch a
working plugin off before recovery has linked them again ("component failed to load"). Recovery
re-applies every plugin the safety net switched off, and every plugin taken off with one of those
because it needs it; the safety net then judges them again with everything linked, and only the
ones that still fail stay off. A plugin a person switched off, one the safety net switched off
during a recovery, and one a recovery could not put back stay off.
"""

from pathlib import Path

from ..manifest import installed_manifest_dirs
from ..switched_off_marker import (
    AUTO_DEACTIVATED_PREFIX,
    provider_that_stranded,
    switched_off_reason,
)


def plugins_to_put_back(plugin_root: Path) -> list[Path]:
    """The switched-off plugins recovery re-applies, in the plugin root's order."""
    reasons = {plugin_dir: reason for plugin_dir in installed_manifest_dirs(plugin_root)
               if (reason := switched_off_reason(plugin_dir)) is not None}
    by_the_net = {plugin_dir.name for plugin_dir, reason in reasons.items()
                  if reason.startswith(AUTO_DEACTIVATED_PREFIX)}
    put_back = _with_the_plugins_they_took_along(by_the_net, reasons)
    return [plugin_dir for plugin_dir in reasons if plugin_dir.name in put_back]


def _with_the_plugins_they_took_along(by_the_net: set[str], reasons: dict[Path, str]) -> set[str]:
    """`by_the_net` grown by every plugin switched off with a plugin in it, until none is added."""
    put_back = by_the_net
    while True:
        taken_along = {plugin_dir.name for plugin_dir, reason in reasons.items()
                       if provider_that_stranded(reason) in put_back} - put_back
        if not taken_along:
            return put_back
        put_back = put_back | taken_along
