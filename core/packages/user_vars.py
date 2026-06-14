"""User variables: validation, the $VAR expander, persistence, the per-plugin venv var, and the
required-variable check.

A plugin's install templates and commands interpolate `$NAME` values the user supplied at install
time. These are persisted next to the plugin so reconfigure, update, and recover can re-expand them.
"""

import json
import re
from pathlib import Path
from typing import cast

from .. import python_env

# The comma is allowed for list-valued config (e.g. NOTIFY_EVENTS="complete,error,cancelled"). It is
# safe in the shell-interpolated `install.start` commands: a bare comma is not a metacharacter, and
# brace expansion (its only special use) needs `{`/`}`, which this allowlist already blocks.
_SAFE_VAR_RE = re.compile(r'^[A-Za-z0-9 .,\-:/_@]+$')
_SAFE_VAR_ALLOWED = "letters, numbers, spaces, and . , - : / _ @"

USER_VARS_FILE = "user_vars.json"


def validate_user_vars(user_vars: dict[str, str]) -> None:
    for key, value in user_vars.items():
        if not _SAFE_VAR_RE.match(value):
            raise ValueError(f"Variable {key!r} allows only {_SAFE_VAR_ALLOWED}. Got: {value!r}")


def expand(template: str, vars: dict[str, str]) -> str:
    expanded = template
    for key in sorted(vars, key=len, reverse=True):
        expanded = expanded.replace(f"${key}", vars[key])
    return expanded


def persist_user_vars(plugin_dir: Path, user_vars: dict[str, str]) -> None:
    if not user_vars:
        return
    (plugin_dir / USER_VARS_FILE).write_text(json.dumps(user_vars))


def load_user_vars(plugin_dir: Path) -> dict[str, str]:
    path = plugin_dir / USER_VARS_FILE
    if not path.exists():
        return {}
    return cast(dict[str, str], json.loads(path.read_text()))


def with_plugin_venv(vars: dict[str, str], plugin_id: str) -> dict[str, str]:
    """Expose the deterministic per-plugin venv path as $PLUGIN_VENV for service commands."""
    venv_path = python_env.plugin_venv_path(vars.get("BESPOK3D", ""), plugin_id)
    return {**vars, python_env.PLUGIN_VENV_VAR: str(venv_path)}


def missing_required_vars(manifest: dict, available: dict[str, str]) -> list[str]:
    specs = manifest.get("requires", {}).get("variables", [])
    return [spec["name"] for spec in specs if spec.get("required") and not available.get(spec["name"])]  # noqa: E501
