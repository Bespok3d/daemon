# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The reasons a single install is declined before a single file is placed, and the cleanup each
one owes the printer.

A refusal is not a failed install: the package was understood and rejected, so the printer must end
up exactly as it was, with the extraction taken back off again.
"""

from pathlib import Path
from typing import NoReturn

from .dependencies import installed_conflicts, unsatisfied_requirements
from .errors import ConflictError, MissingSettingError, RequirementError
from .extraction import discard_extraction
from .user_vars import refuse_missing_settings


def refuse_and_discard(plugin_dir: Path, refusal: Exception) -> NoReturn:
    """A refused install takes its own extraction with it."""
    discard_extraction(plugin_dir)
    raise refusal


def refuse_unmet_dependencies(
    plugin_root: Path,
    plugin_dir: Path,
    plugin_id: str,
    manifest: dict,
) -> None:
    """A plugin that collides with an installed one, or one whose required service is absent."""
    conflicts = installed_conflicts(plugin_root, plugin_id, manifest)
    if conflicts:
        refuse_and_discard(plugin_dir, ConflictError(plugin_id, conflicts))

    missing = unsatisfied_requirements(plugin_root, plugin_id, manifest)
    if missing:
        refuse_and_discard(plugin_dir, RequirementError(plugin_id, missing))


def refuse_unset_settings(plugin_dir: Path, manifest: dict, full_vars: dict[str, str]) -> None:
    """A setting the package says it needs, arriving with no value, is a refusal and not an install
    that half works: the config it would write names the setting instead of holding its value."""
    try:
        refuse_missing_settings(manifest, full_vars)
    except MissingSettingError as unset:
        refuse_and_discard(plugin_dir, unset)
