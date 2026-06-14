"""Errors raised when an install or uninstall is refused by the dependency graph."""


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
