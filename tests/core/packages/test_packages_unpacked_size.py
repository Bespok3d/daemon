# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A package is refused when it would not fit on the printer with working space left over.

Without this, an upload sized to the disk fills it, and a full disk takes Klipper down with the
daemon: the printer stops printing because someone installed a plugin.
"""

import shutil
import zipfile
from pathlib import Path

import pytest

from core.packages import archive, unpacked_size
from tests.package_fixtures import package_bytes

MP = pytest.MonkeyPatch


def _package_with_a_payload(path: Path, payload: str) -> Path:
    path.write_bytes(package_bytes(
        {"name": "alpha", "version": "1.0", "install": {"start": []}},
        {"files/run.sh": payload},
    ))
    return path


def _pretend_free_space(monkeypatch: MP, free_bytes: int) -> None:
    def usage(_path: str) -> shutil._ntuple_diskusage:
        return shutil._ntuple_diskusage(total=free_bytes, used=0, free=free_bytes)

    monkeypatch.setattr(unpacked_size.shutil, "disk_usage", usage)


def test_unpacked_size_totals_what_the_members_write_out(tmp_path: Path) -> None:
    package = _package_with_a_payload(tmp_path / "p.b3", "x" * 5000)
    with zipfile.ZipFile(package) as opened:
        assert unpacked_size.unpacked_size(opened, ["files/run.sh"]) == 5000


def test_unpacked_size_ignores_members_that_are_not_deployed(tmp_path: Path) -> None:
    """doc/ never lands on the printer, so it never counts against the printer's space."""
    package = tmp_path / "p.b3"
    package.write_bytes(package_bytes(
        {"name": "alpha", "version": "1.0", "install": {"start": []}},
        {"files/run.sh": "hi", "doc/README.md": "y" * 9000},
    ))
    with zipfile.ZipFile(package) as opened:
        assert unpacked_size.unpacked_size(opened, ["files/run.sh"]) == 2


def test_free_space_reads_the_nearest_parent_that_exists(tmp_path: Path) -> None:
    """A first install names a plugin root the install itself creates, so the answer must come from
    a parent rather than raising on the missing directory."""
    assert unpacked_size.free_space(tmp_path / "plugins" / "alpha") > 0


def test_a_package_larger_than_the_free_space_is_refused(tmp_path: Path, monkeypatch: MP) -> None:
    package = _package_with_a_payload(tmp_path / "p.b3", "x" * 5000)
    _pretend_free_space(monkeypatch, 4000)
    with zipfile.ZipFile(package) as opened:
        with pytest.raises(ValueError, match="MB free"):
            unpacked_size.refuse_package_that_does_not_fit(opened, tmp_path, ["files/run.sh"])


def test_a_package_that_would_eat_the_reserve_is_refused(tmp_path: Path, monkeypatch: MP) -> None:
    """It fits by the raw numbers and is still refused: the printer keeps room to work in."""
    package = _package_with_a_payload(tmp_path / "p.b3", "x" * 5000)
    _pretend_free_space(monkeypatch, unpacked_size.FREE_SPACE_RESERVE_BYTES + 4000)
    with zipfile.ZipFile(package) as opened:
        with pytest.raises(ValueError, match="working space"):
            unpacked_size.refuse_package_that_does_not_fit(opened, tmp_path, ["files/run.sh"])


def test_a_package_that_fits_with_the_reserve_free_is_accepted(tmp_path: Path, monkeypatch: MP) -> None:  # noqa: E501
    package = _package_with_a_payload(tmp_path / "p.b3", "x" * 5000)
    _pretend_free_space(monkeypatch, unpacked_size.FREE_SPACE_RESERVE_BYTES + 6000)
    with zipfile.ZipFile(package) as opened:
        unpacked_size.refuse_package_that_does_not_fit(opened, tmp_path, ["files/run.sh"])


def test_unpack_refuses_before_the_plugin_dir_is_created(tmp_path: Path, monkeypatch: MP) -> None:
    """The refusal leaves the disk exactly as it was: no directory, no partial tree to walk back."""
    package = _package_with_a_payload(tmp_path / "p.b3", "x" * 5000)
    plugin_root = tmp_path / "plugins"
    _pretend_free_space(monkeypatch, 4000)
    with pytest.raises(ValueError):
        archive.unpack_package(plugin_root, package)
    assert not (plugin_root / "alpha").exists()
