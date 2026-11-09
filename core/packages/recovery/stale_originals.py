# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The kept originals of the plugins that stay switched off through a recovery, settled against the
new firmware's files.

A plugin switched off before a firmware update keeps its copies, and removing it later writes them
back, so recovery settles them the way a switch-off does (`settle_originals`). On a torn manifest
(it names no patches) or a failed check, every copy of the plugin is dropped, so an error never
leaves an old firmware's file to write back.
"""

from pathlib import Path

from ..batch_rows import failed_result
from ..manifest import readable_manifest
from ..settle_originals import (
    COPIES_REMOVED_UNCHECKED,
    drop_kept_originals,
    settle_or_drop_kept_originals,
)


def settle_kept_originals_of_switched_off(plugin_dirs: list[Path],
                                          vars: dict[str, str]) -> list[dict]:
    """Settle the kept originals of every plugin in `plugin_dirs`, the ones that stay switched off.
    Returns a failed row for each plugin whose copies could not be checked."""
    checks = [_settle_switched_off(plugin_dir, vars) for plugin_dir in plugin_dirs]
    return [failure for failure in checks if failure is not None]


def _settle_switched_off(plugin_dir: Path, vars: dict[str, str]) -> dict | None:
    manifest = readable_manifest(plugin_dir)
    if manifest is None:
        drop_kept_originals(plugin_dir)
        return None
    check_error = settle_or_drop_kept_originals(plugin_dir, manifest, vars)
    if check_error is None:
        return None
    return failed_result(plugin_dir.name, f"{COPIES_REMOVED_UNCHECKED}: {check_error}", [])
