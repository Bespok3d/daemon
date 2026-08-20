# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A member that unpacks to more than it declared is refused, and takes its extraction with it.

Every size check the printer runs before it writes a byte reads what the archive DECLARES. A
member whose compressed stream really holds far more than that gets past all of them and only
fails while it is being written, and the flash can fill up mid write whatever the package
declared. What must not survive either failure is a half written plugin directory: kept, the
daemon would report a plugin it never installed.
"""

from pathlib import Path

import pytest

from core.packages import archive
from tests.package_fixtures import package_bytes
from tests.zip_declaration import unpacked_sizes_declared_as

BYTES_DECLARED = 100
CONTENT_REALLY_IN_THE_STREAM = "x" * 200_000


def _package_whose_member_lies_about_its_size(path: Path) -> Path:
    honest = package_bytes(
        {"name": "alpha", "version": "1.0", "install": {"start": []}},
        {"files/run.sh": CONTENT_REALLY_IN_THE_STREAM},
    )
    path.write_bytes(unpacked_sizes_declared_as(honest, BYTES_DECLARED, {"manifest.json"}))
    return path


def test_a_member_unpacking_to_more_than_it_declared_is_refused(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugins"

    with pytest.raises(ValueError, match="did not unpack"):
        archive.unpack_package(
            plugin_root, _package_whose_member_lies_about_its_size(tmp_path / "p.b3"),
        )

    assert not (plugin_root / "alpha").exists()


def test_the_install_it_would_have_replaced_keeps_its_stock_originals(tmp_path: Path) -> None:
    """The plugin directory holds the only copy of the stock files the version on the printer
    patched, so a package that dies mid write must not take that directory with it."""
    plugin_root = tmp_path / "plugins"
    installed = plugin_root / "alpha"
    (installed / "patches_orig").mkdir(parents=True)
    (installed / "patches_orig" / "printer.cfg").write_text("stock printer.cfg")
    (installed / "user_vars.json").write_text('{"port": "7125"}')

    with pytest.raises(ValueError, match="did not unpack"):
        archive.unpack_package(
            plugin_root, _package_whose_member_lies_about_its_size(tmp_path / "p.b3"),
        )

    assert (installed / "patches_orig" / "printer.cfg").read_text() == "stock printer.cfg"
    assert (installed / "user_vars.json").read_text() == '{"port": "7125"}'


def test_the_flash_filling_up_mid_write_leaves_nothing_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The declared sizes can be honest and the write still fail: another process can take the last
    of the flash between the space check and the extraction."""
    def out_of_space(*_args: object, **_kwargs: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("zipfile.ZipFile.extract", out_of_space)
    package = tmp_path / "p.b3"
    package.write_bytes(package_bytes(
        {"name": "alpha", "version": "1.0", "install": {"start": []}},
        {"files/run.sh": "echo hi"},
    ))
    plugin_root = tmp_path / "plugins"

    with pytest.raises(ValueError, match="No space left on device"):
        archive.unpack_package(plugin_root, package)

    assert not (plugin_root / "alpha").exists()
