"""Run a plugin's install start commands, deferring core-service restarts to a batch.

A plugin's start commands run immediately, EXCEPT init-script/nginx service actions, which are
returned as `deferred` so the caller runs them once at the end (and through the safety net) instead
of bouncing the core services per plugin. Shared by every install-like path: install, reconfigure,
update, and OTA recover. The daemon resolves and splits the commands; the jinni RUNS them (ADR-0037:
executing a device command is the jinni's actuation, never the daemon's).
"""

from .. import jinni_client
from ..results import item, phase
from .user_vars import expand


def run_plugin_start_commands(cmds: list[str], vars: dict[str, str]) -> tuple[dict, list[str]]:
    expanded_cmds = [expand(cmd, vars) for cmd in cmds]
    effects = jinni_client.classify_commands(expanded_cmds)
    immediate = [cmd for cmd, effect in zip(expanded_cmds, effects) if not effect.deferrable]
    deferred = [cmd for cmd, effect in zip(expanded_cmds, effects) if effect.deferrable]
    results = jinni_client.run_actions(immediate)
    items = [item(cmd, ok=result.ok, output=result.output) for cmd, result in zip(immediate, results)]  # noqa: E501
    return phase("start", "Start commands", items), deferred
