# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""One package's turn inside a batch: unpack it, settle the config it will be applied with, run its
install phases and defer its restart.

A failure here is contained to this plugin (recover_one's pattern), so the rest of the batch still
completes. The loop that calls this, and the single restart at the end, live in `batch.py`.
"""

from pathlib import Path

from ..results import item, phase
from .archive import unpack_package
from .batch_rows import failed_result, install_error
from .deactivation import deactivate_plugin, finalize_install_outcome
from .errors import MissingSettingError
from .extraction import discard_extraction
from .file_drift import refuse_changed_package
from .installer import PhaseListener, apply_install_deferred
from .integrity import IntegrityError
from .user_vars import (
    persist_user_vars,
    refuse_missing_settings,
    with_declared_defaults,
    with_plugin_venv,
)


def _unpacked_for_apply(
    plugin_root: Path,
    base_vars: dict[str, str],
    package_path: Path,
    user_vars: dict[str, str],
    notify: PhaseListener,
) -> tuple[dict, Path, dict[str, str], dict]:
    """Put one package's files on disk, save the config the user typed with them, and announce the
    extract phase: everything the apply below needs before it runs a single install phase."""
    manifest, plugin_dir, file_count = unpack_package(plugin_root, package_path)
    settings = with_declared_defaults(manifest, user_vars)
    full_vars = with_plugin_venv({**base_vars, **settings}, manifest["name"])
    persist_user_vars(plugin_dir, settings)
    extract = phase("extract", "Unpack", [item(f"Extracted {file_count} files", ok=True)])
    notify(extract)
    return manifest, plugin_dir, full_vars, extract


def apply_one(
    plugin_root: Path,
    base_vars: dict[str, str],
    package_path: Path,
    user_vars: dict[str, str],
    notify: PhaseListener,
) -> tuple[dict, list[str]]:
    """Apply one package's install, deferring its restart. A failure is contained to this plugin
    (recover_one's pattern): a raised or failed-phase apply deactivates it and returns a failed
    result, so the rest of the batch still completes."""
    manifest, plugin_dir, full_vars, extract = _unpacked_for_apply(
        plugin_root, base_vars, package_path, user_vars, notify,
    )
    plugin_id = manifest["name"]
    try:
        refuse_missing_settings(manifest, full_vars)
        refuse_changed_package(plugin_dir, manifest)
        phases, deferred = apply_install_deferred(
            plugin_root, plugin_dir, manifest, full_vars, notify,
        )
    except (IntegrityError, MissingSettingError) as refused_package:
        # Same cleanup a single install does: a package whose contents belie its manifest, or that
        # arrived without a value it says it needs, leaves nothing on the printer rather than a
        # deactivated tree the daemon never applied.
        discard_extraction(plugin_dir)
        return failed_result(plugin_id, install_error(refused_package), [extract]), []
    except Exception as exc:  # noqa: BLE001 - one plugin's apply error must NOT abort the batch
        reason = install_error(exc)
        deactivate_plugin(plugin_dir, full_vars, reason)
        return failed_result(plugin_id, reason, [extract]), []
    log = [extract, *phases]
    finalize_install_outcome(plugin_dir, full_vars, log)
    ok = all(logged_phase["ok"] for logged_phase in log)
    reason = "" if ok else "update phase failed"
    result = {"plugin_id": plugin_id, "ok": ok, "skipped": False, "reason": reason, "log": log}
    return result, (deferred if ok else [])
