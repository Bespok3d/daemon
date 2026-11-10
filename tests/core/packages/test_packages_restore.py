# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Putting back an installed plugin's changed files from a zip of just those files.

The installed manifest is what vouches for every file in the zip, so a file it does not list as kept
on disk, a file whose folder leads outside the plugin dir, or a file whose bytes differ from the
listed sha256 refuses the whole zip before a byte is written. A running print refuses it too.
"""

import os
from pathlib import Path

import pytest

from core.packages.errors import BlockedActionError
from core.packages.integrity import (
    CHECKSUM_MISMATCH,
    ESCAPING_MEMBER,
    UNDECLARED_MEMBER,
    IntegrityError,
)
from tests.core.packages.fake_changed_plugin import (
    BINARY,
    CHANGED_BINARY,
    CHANGED_SETTINGS,
    RENDERED,
    SETTINGS,
    SIGNED_BINARY,
    SIGNED_SETTINGS,
    USER_RENDERED,
    installed,
    restore_from,
    zip_of,
)
from tests.fakes import FakeKlipperJinni


def test_the_signed_files_are_written_back_and_named(tmp_path: Path) -> None:
    plugin_dir = installed(tmp_path)
    archive_path = zip_of(tmp_path, {SETTINGS: SIGNED_SETTINGS, BINARY: SIGNED_BINARY})

    restored = restore_from(plugin_dir, archive_path)

    assert restored == [BINARY, SETTINGS]
    assert (plugin_dir / BINARY).read_bytes() == SIGNED_BINARY
    assert (plugin_dir / SETTINGS).read_bytes() == SIGNED_SETTINGS
    assert (plugin_dir / BINARY).stat().st_mode & 0o777 == 0o755


def test_only_the_files_in_the_zip_are_touched(tmp_path: Path) -> None:
    plugin_dir = installed(tmp_path)

    restore_from(plugin_dir, zip_of(tmp_path, {SETTINGS: SIGNED_SETTINGS}))

    assert (plugin_dir / SETTINGS).read_bytes() == SIGNED_SETTINGS
    assert (plugin_dir / BINARY).read_bytes() == CHANGED_BINARY
    assert (plugin_dir / RENDERED).read_bytes() == USER_RENDERED


@pytest.mark.parametrize("unsigned_member", ["manifest.json", "files/extra.sh", RENDERED])
def test_a_file_the_manifest_does_not_keep_refuses_the_zip_whole(
    tmp_path: Path, unsigned_member: str,
) -> None:
    """A render target is listed, but install writes it from the template and the user's settings,
    so writing the placeholder back would throw those settings away."""
    plugin_dir = installed(tmp_path)
    archive_path = zip_of(tmp_path, {SETTINGS: SIGNED_SETTINGS, unsigned_member: b"anything"})

    with pytest.raises(IntegrityError) as refusal:
        restore_from(plugin_dir, archive_path)

    assert (refusal.value.reason, refusal.value.paths) == (UNDECLARED_MEMBER, [unsigned_member])
    assert (plugin_dir / SETTINGS).read_bytes() == CHANGED_SETTINGS


def test_a_file_whose_bytes_differ_from_the_signed_ones_refuses_the_zip_whole(
    tmp_path: Path,
) -> None:
    plugin_dir = installed(tmp_path)
    archive_path = zip_of(tmp_path, {SETTINGS: SIGNED_SETTINGS, BINARY: b"not the signed one"})

    with pytest.raises(IntegrityError) as refusal:
        restore_from(plugin_dir, archive_path)

    assert (refusal.value.reason, refusal.value.paths) == (CHECKSUM_MISMATCH, [BINARY])
    assert (plugin_dir / SETTINGS).read_bytes() == CHANGED_SETTINGS


def test_a_file_whose_folder_now_leads_out_of_the_plugin_dir_is_refused(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins/spoolman"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "files").symlink_to(elsewhere)

    with pytest.raises(IntegrityError) as refusal:
        restore_from(plugin_dir, zip_of(tmp_path, {SETTINGS: SIGNED_SETTINGS}))

    assert (refusal.value.reason, refusal.value.paths) == (ESCAPING_MEMBER, [SETTINGS])
    assert not (elsewhere / "settings.cfg").exists()


def test_a_file_now_linked_out_of_the_plugin_dir_is_put_back_in_place_of_the_link(
    tmp_path: Path,
) -> None:
    """The hashes route answers such a file as missing, so this is the zip the app sends back."""
    plugin_dir = installed(tmp_path)
    elsewhere = tmp_path / "elsewhere.cfg"
    elsewhere.write_bytes(b"another file on the printer")
    (plugin_dir / SETTINGS).unlink()
    (plugin_dir / SETTINGS).symlink_to(elsewhere)

    restored = restore_from(plugin_dir, zip_of(tmp_path, {SETTINGS: SIGNED_SETTINGS}))

    assert restored == [SETTINGS]
    assert not (plugin_dir / SETTINGS).is_symlink()
    assert (plugin_dir / SETTINGS).read_bytes() == SIGNED_SETTINGS
    assert elsewhere.read_bytes() == b"another file on the printer"


def test_a_fifo_at_a_kept_path_is_replaced_not_written_into(tmp_path: Path) -> None:
    """Opened to be filled, a fifo would hang the root daemon until something read it."""
    plugin_dir = installed(tmp_path)
    (plugin_dir / SETTINGS).unlink()
    os.mkfifo(plugin_dir / SETTINGS)

    restore_from(plugin_dir, zip_of(tmp_path, {SETTINGS: SIGNED_SETTINGS}))

    assert (plugin_dir / SETTINGS).read_bytes() == SIGNED_SETTINGS


def test_a_running_print_refuses_the_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(FakeKlipperJinni, "print_active", lambda _jinni: (True, "printing"))
    plugin_dir = installed(tmp_path)

    with pytest.raises(BlockedActionError):
        restore_from(plugin_dir, zip_of(tmp_path, {SETTINGS: SIGNED_SETTINGS}))

    assert (plugin_dir / SETTINGS).read_bytes() == CHANGED_SETTINGS
