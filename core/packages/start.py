"""Run a plugin's install start commands, deferring core-service restarts to a batch.

A plugin's start commands run immediately, EXCEPT init-script/nginx service actions, which are
returned as `deferred` so the caller runs them once at the end (and through the safety net) instead
of bouncing Klipper/Moonraker per plugin. Shared by every install-like path: install, reconfigure,
update, and OTA recover.
"""

from ..intent import is_service_action
from ..results import phase
from ..shell import run_one_command, start_env
from .user_vars import expand


def run_plugin_start_commands(cmds: list[str], vars: dict[str, str]) -> tuple[dict, list[str]]:
    env = start_env()
    expanded_cmds = [expand(cmd, vars) for cmd in cmds]
    immediate = [cmd for cmd in expanded_cmds if not is_service_action(cmd)]
    deferred = [cmd for cmd in expanded_cmds if is_service_action(cmd)]
    items = [run_one_command(cmd, env) for cmd in immediate]
    return phase("start", "Start commands", items), deferred
