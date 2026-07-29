# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the daemon was doing when it asked the safety net to keep watch.

The daemon performs a risky operation (an install, an update, an OTA recover) and hands this context
to the safety net. The net uses it to report in plain words and, when it cannot pin the failure on a
specific plugin, to name the one the operation was about as the likely culprit.
"""
from dataclasses import dataclass
from enum import Enum


class OperationKind(str, Enum):
    INSTALL = "install"
    RECONFIGURE = "reconfigure"
    RECOVER = "recover"
    UPDATE = "update"
    UNINSTALL = "uninstall"
    TEARDOWN = "teardown"


_ACTION_TEMPLATES = {
    OperationKind.INSTALL: "installing {plugin}",
    OperationKind.RECONFIGURE: "reconfiguring {plugin}",
    OperationKind.UPDATE: "updating {plugin}",
    OperationKind.UNINSTALL: "uninstalling {plugin}",
}


@dataclass(frozen=True)
class OperationContext:
    kind: OperationKind
    plugin_id: str | None = None
    plugin_version: str | None = None
    publisher: str | None = None

    def human_action(self) -> str:
        """A plain-words description of the operation for user-facing messages."""
        if self.kind == OperationKind.TEARDOWN:
            return "removing Bespok3d"
        if self.kind == OperationKind.RECOVER or self.plugin_id is None:
            return "recovering your plugins"
        plugin = self.plugin_id
        if self.plugin_version:
            plugin = f"{plugin} {self.plugin_version}"
        return _ACTION_TEMPLATES[self.kind].format(plugin=plugin)
