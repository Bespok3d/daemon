# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Errors raised when a plugin op is refused: by the dependency graph, or by the print guard."""


class BlockedActionError(Exception):
    """A plugin op was refused because an action it needs is blocked on the printer right now (a
    print is running). Carries the blocked-action TOKENS; the daemon relays them and the CLIENT
    localizes (ADR-0037). The message lists tokens for the daemon's own logs, never for the user."""

    def __init__(self, blocked: frozenset[str]) -> None:
        self.blocked = sorted(blocked)
        super().__init__(f"blocked actions: {', '.join(self.blocked)}")


class DependentsError(Exception):
    """Uninstall was refused because installed plugins still depend on the target."""

    def __init__(self, plugin_id: str, dependents: list[str]) -> None:
        self.plugin_id = plugin_id
        self.dependents = dependents
        super().__init__(f"{plugin_id} is required by: {', '.join(dependents)}")


class ConflictError(Exception):
    """Install was refused because the package conflicts with an installed plugin."""

    def __init__(self, plugin_id: str, conflicts: list[str]) -> None:
        self.plugin_id = plugin_id
        self.conflicts = conflicts
        super().__init__(f"{plugin_id} conflicts with installed: {', '.join(conflicts)}")


class RequirementError(Exception):
    """Install was refused because a service the package requires is provided by no installed,
    non-deactivated plugin (nor, in a batch, by a sibling in the same batch)."""

    def __init__(self, plugin_id: str, missing: list[str]) -> None:
        self.plugin_id = plugin_id
        self.missing = missing
        super().__init__(f"{plugin_id} requires uninstalled service(s): {', '.join(missing)}")


class IncompatiblePairError(Exception):
    """A plugin op was refused because the daemon and the jinni on this printer are a pair the
    daemon will not drive. Carries WHICH SIDE is behind and the two versions as machine values; the
    daemon relays facts and never prose (ADR-0037), so the client writes the sentence the user
    reads. The message is for the daemon's own logs."""

    def __init__(self, side: str, required: str, running: str) -> None:
        self.side = side
        self.required = required
        self.running = running
        super().__init__(f"{side} {running} is older than the required {required}")
