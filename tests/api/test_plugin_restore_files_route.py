# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Putting back an installed plugin's changed files from a zip of just those files, at the HTTP
boundary the app calls."""
import io
import zipfile
from pathlib import Path

import pytest

from core import packages
from core.packages import restore
from core.packages.integrity import CHECKSUM_MISMATCH, UNDECLARED_MEMBER
from core.results import item, phase
from tests.api.fake_spoolman_files import (
    CHANGED_SETTINGS,
    SETTINGS,
    SIGNED_SETTINGS,
    installed,
    restore_from,
    zip_of,
)
from tests.fakes import FakeKlipperJinni

pytestmark = pytest.mark.usefixtures("daemon_acl")

_LOCAL_HEADER_SIZE = 30
# BFINAL set with the reserved block type, a deflate stream zlib refuses to decode.
_RESERVED_DEFLATE_BLOCK = 0xFF


def _ownership_fixed(plugin_dir: Path, runtime_user: str) -> dict:
    chown = item(f"chown -R {runtime_user} {plugin_dir.name}", ok=True)
    return phase("ownership", "Permissions", [chown])


def _signed_settings_with_a_damaged_stream() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as restore_zip:
        restore_zip.writestr(SETTINGS, SIGNED_SETTINGS)
    damaged = bytearray(buffer.getvalue())
    damaged[_LOCAL_HEADER_SIZE + len(SETTINGS)] = _RESERVED_DEFLATE_BLOCK
    return bytes(damaged)


@pytest.fixture(autouse=True)
def _served_from_the_test_plugin_root(
    plugin_root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", plugin_root)
    monkeypatch.setattr(restore, "fix_ownership", _ownership_fixed)


async def test_the_signed_file_is_put_back(plugin_root: Path) -> None:
    plugin_dir = installed(plugin_root)

    response = await restore_from("spoolman", zip_of({SETTINGS: SIGNED_SETTINGS}))

    assert (response.status_code, response.json()) == (200, {"restored": [SETTINGS]})
    assert (plugin_dir / SETTINGS).read_bytes() == SIGNED_SETTINGS


@pytest.mark.parametrize(
    ("restore_members", "reason", "refused_path"),
    [
        ({SETTINGS: b"not the signed bytes"}, CHECKSUM_MISMATCH, SETTINGS),
        ({SETTINGS: SIGNED_SETTINGS, "files/extra.sh": b"echo"}, UNDECLARED_MEMBER,
         "files/extra.sh"),
    ],
)
async def test_an_unsigned_zip_is_refused_with_the_integrity_refusal(
    plugin_root: Path, restore_members: dict[str, bytes], reason: str, refused_path: str,
) -> None:
    plugin_dir = installed(plugin_root)

    response = await restore_from("spoolman", zip_of(restore_members))

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "error": "integrity", "plugin_id": "spoolman", "reason": reason, "paths": [refused_path],
    }
    assert (plugin_dir / SETTINGS).read_bytes() == CHANGED_SETTINGS


async def test_a_running_print_refuses_the_restore(
    plugin_root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(FakeKlipperJinni, "print_active", lambda _jinni: (True, "printing"))
    plugin_dir = installed(plugin_root)

    response = await restore_from("spoolman", zip_of({SETTINGS: SIGNED_SETTINGS}))

    assert response.status_code == 409
    assert response.json()["error"] == "blocked"
    assert (plugin_dir / SETTINGS).read_bytes() == CHANGED_SETTINGS


async def test_an_upload_that_is_not_a_zip_is_a_bad_request(plugin_root: Path) -> None:
    installed(plugin_root)

    response = await restore_from("spoolman", b"not a zip")

    assert response.status_code == 400
    assert "did not unpack" in response.json()["detail"]


async def test_a_member_whose_stream_is_damaged_is_a_bad_request(plugin_root: Path) -> None:
    plugin_dir = installed(plugin_root)

    response = await restore_from("spoolman", _signed_settings_with_a_damaged_stream())

    assert response.status_code == 400
    assert "did not unpack" in response.json()["detail"]
    assert (plugin_dir / SETTINGS).read_bytes() == CHANGED_SETTINGS
