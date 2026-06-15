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
