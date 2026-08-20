# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The one resolver from an outside-supplied plugin id to the directory it names.

The daemon runs as root, so every id that arrives from a route path param, a request body, or a
package manifest is untrusted until it has been through here: an id carrying a separator or `..`
would otherwise relocate a delete or a write outside the tree it was meant to touch (Starlette's
`[^/]+` path-param regex happily matches a bare `..`).

The rule itself lives in `stays_inside_its_parent_dir`; this module is only where the refusal is
raised, so there is one place to read and one place to change.
"""

from pathlib import Path

from .integrity import ESCAPING_PLUGIN_ID, IntegrityError
from .members import stays_inside_its_parent_dir


def contained_plugin_dir(root: Path, plugin_id: object) -> Path:
    """The directory `plugin_id` names directly inside `root`, or a refusal if it names anything
    else. `root` is whichever tree holds one directory per plugin: the plugin root for an install,
    the per-plugin venv root for a venv."""
    if stays_inside_its_parent_dir(plugin_id):
        return root / plugin_id
    raise IntegrityError(str(plugin_id), ESCAPING_PLUGIN_ID, [str(plugin_id)])
