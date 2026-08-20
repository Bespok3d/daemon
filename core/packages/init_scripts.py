# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Write a generated init.d script into a plugin's tree, shared by the managed-service and
kernel-module loaders.

Both concerns ask the jinni to render a boot script (a service init script, a module loader) and
drop it under the plugin's `etc/init.d` before the daemon wires the autostart symlink. The gating on
the printer's capability flag and the script CONTENT belong to each caller; this owns only the write
mechanic (containment, parent dir, write, executable mode) and the per-script phase item, so the two
callers do not carry a second copy of it.

The script name is manifest input: a service or kernel module names itself and the daemon renders
that name into a boot script the printer runs as root at every boot. Containment is the same rule
the package members answer to, so it is the same function.
"""

from collections.abc import Callable
from pathlib import Path

from ..autostart import SERVICE_SCRIPT_DIR
from ..results import item
from .members import stays_inside_its_parent_dir

ESCAPING_SCRIPT_NAME = "not a script name inside the plugin's own init.d dir"


def write_init_script(plugin_dir: Path, script_name: str, render: Callable[[], str]) -> dict:
    """Render the script and write it executable under the plugin's init.d dir, reporting the
    outcome as one phase item. `render` is a thunk so a render error is reported, never raised."""
    if not stays_inside_its_parent_dir(script_name):
        return item(f"{script_name}: {ESCAPING_SCRIPT_NAME}", ok=False)
    target = plugin_dir / SERVICE_SCRIPT_DIR / script_name
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render())
        target.chmod(0o755)
    except Exception as exc:
        return item(f"{script_name}: {exc}", ok=False)
    return item(script_name, ok=True)
