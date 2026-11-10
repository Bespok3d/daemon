# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A restore the printer could not finish: a zip that does not fit, a file that cannot be written,
a folder link that loops, or permissions that could not be fixed afterwards. Each one is reported,
and the files already written are still handed to the plugin's user."""

from pathlib import Path

import pytest

from core.packages import restore, unpacked_size
from core.packages.integrity import ESCAPING_MEMBER, IntegrityError
from core.results import item, phase
from tests.core.packages.fake_changed_plugin import (
    BINARY,
    CHANGED_SETTINGS,
    SETTINGS,
    SIGNED_BINARY,
    SIGNED_SETTINGS,
    installed,
    restore_from,
    zip_of,
)


def _failing_ownership(plugin_dir: Path, runtime_user: str) -> dict:
    return phase("ownership", "Permissions", [item("chown -R lava spoolman", ok=False)])


class _RecordingOwnership:
    """A fix_ownership double that records the plugin dirs it was run over."""

    def __init__(self) -> None:
        self.fixed_dirs: list[Path] = []

    def __call__(self, plugin_dir: Path, runtime_user: str) -> dict:
        self.fixed_dirs.append(plugin_dir)
        return phase("ownership", "Permissions", [item("chmod -R 755 spoolman", ok=True)])


def _settings_turned_into_a_folder(plugin_dir: Path) -> None:
    (plugin_dir / SETTINGS).unlink()
    (plugin_dir / SETTINGS).mkdir()


def test_a_failed_permission_fix_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(restore, "fix_ownership", _failing_ownership)
    plugin_dir = installed(tmp_path)

    with pytest.raises(RuntimeError, match="wrong permissions"):
        restore_from(plugin_dir, zip_of(tmp_path, {SETTINGS: SIGNED_SETTINGS}))

    assert (plugin_dir / SETTINGS).read_bytes() == SIGNED_SETTINGS


def test_a_file_that_cannot_be_written_is_a_printer_fault_not_a_bad_zip(tmp_path: Path) -> None:
    """The zip was signed and unpacked fine; the printer could not write it, so it is not the
    caller's request that was wrong."""
    plugin_dir = installed(tmp_path)
    _settings_turned_into_a_folder(plugin_dir)

    with pytest.raises(OSError):
        restore_from(plugin_dir, zip_of(tmp_path, {SETTINGS: SIGNED_SETTINGS}))


def test_a_write_that_fails_part_way_still_fixes_the_ownership_of_what_was_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ownership = _RecordingOwnership()
    monkeypatch.setattr(restore, "fix_ownership", ownership)
    plugin_dir = installed(tmp_path)
    _settings_turned_into_a_folder(plugin_dir)
    archive_path = zip_of(tmp_path, {BINARY: SIGNED_BINARY, SETTINGS: SIGNED_SETTINGS})

    with pytest.raises(OSError):
        restore_from(plugin_dir, archive_path)

    assert (plugin_dir / BINARY).read_bytes() == SIGNED_BINARY
    assert ownership.fixed_dirs == [plugin_dir]


def _no_free_space(_destination: Path) -> int:
    return 0


def test_a_restore_that_does_not_fit_is_refused_before_a_file_is_unlinked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The write unlinks each file before it writes the new one, and a running binary keeps its
    space until it exits, so a full flash mid-write would leave the plugin without that file."""
    monkeypatch.setattr(unpacked_size, "free_space", _no_free_space)
    plugin_dir = installed(tmp_path)

    with pytest.raises(ValueError, match="MB free"):
        restore_from(plugin_dir, zip_of(tmp_path, {SETTINGS: SIGNED_SETTINGS}))

    assert (plugin_dir / SETTINGS).read_bytes() == CHANGED_SETTINGS


def test_a_folder_link_that_loops_is_refused_as_escaping_not_a_printer_fault(
    tmp_path: Path,
) -> None:
    """Nothing shows where a file behind that loop would land, and the plugin's user made it."""
    plugin_dir = installed(tmp_path)
    (plugin_dir / "files").rename(plugin_dir / "kept")
    (plugin_dir / "files").symlink_to("files")

    with pytest.raises(IntegrityError) as refusal:
        restore_from(plugin_dir, zip_of(tmp_path, {SETTINGS: SIGNED_SETTINGS}))

    assert (refusal.value.reason, refusal.value.paths) == (ESCAPING_MEMBER, [SETTINGS])
