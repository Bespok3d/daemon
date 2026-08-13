# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""User variables: rendering to text, validation, the $VAR expander, persistence, the per-plugin
venv var, and the required-variable check.

A plugin's install templates and commands interpolate `$NAME` values the user supplied at install
time. These are persisted next to the plugin so reconfigure, update, and recover can re-expand them.
"""

import json
import re
from pathlib import Path
from typing import cast

from .. import python_env
from .plugin_dir import contained_plugin_dir

# The comma is allowed for list-valued config (e.g. NOTIFY_EVENTS="complete,error,cancelled"). It is
# safe in the shell-interpolated `install.start` commands: a bare comma is not a metacharacter, and
# brace expansion (its only special use) needs `{`/`}`, which this allowlist already blocks.
_SAFE_VAR_RE = re.compile(r'^[A-Za-z0-9 .,\-:/_@]+$')
_SAFE_VAR_ALLOWED = "letters, numbers, spaces, and . , - : / _ @"

USER_VARS_FILE = "user_vars.json"


def user_vars_as_text(supplied: dict[str, object]) -> dict[str, str]:
    """The text form of the values a client sent, which is the only form anything downstream sees.

    A setting is substituted into config text, so it ends up as text whatever it started as. A
    manifest declares a field's type, and a `number` field's value of 5 or a `toggle` field's value
    of true is JSON's own way of writing what those field types mean, so both arrive unquoted and
    both are accepted here rather than refused at the door. Anything the daemon cannot write into a
    config file lands on validate_user_vars, which names the setting the user has to fix.
    """
    return {key: _setting_as_text(value) for key, value in supplied.items()}


def _setting_as_text(value: object) -> str:
    # A toggle is rendered lowercase because that is what a manifest declares as its on/off value.
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


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
    """Expose the deterministic per-plugin venv path as $PLUGIN_VENV for service commands. The id is
    contained first: this value is expanded into commands the printer runs as root."""
    venv_root = python_env.plugin_venv_root(vars.get("BESPOK3D", ""))
    return {**vars, python_env.PLUGIN_VENV_VAR: str(contained_plugin_dir(venv_root, plugin_id))}


def missing_required_vars(manifest: dict, available: dict[str, str]) -> list[str]:
    specs = manifest.get("requires", {}).get("variables", [])
    return [spec["name"] for spec in specs if spec.get("required") and not available.get(spec["name"])]  # noqa: E501
