# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A fault of the printer's own while putting back a plugin's files answers 422, never the 400
that would send the app looking for a fault in the zip it sent."""
import errno
import tempfile
from pathlib import Path
from typing import NoReturn

import pytest

from core import jinni_client, packages
from core.packages import restore
from core.results import item, phase
from tests.api.fake_spoolman_files import (
    CHANGED_SETTINGS,
    SETTINGS,
    SIGNED_SETTINGS,
    installed,
    restore_from,
    zip_of,
)

pytestmark = pytest.mark.usefixtures("daemon_acl")


def _ownership_fixed(plugin_dir: Path, runtime_user: str) -> dict:
    chown = item(f"chown -R {runtime_user} {plugin_dir.name}", ok=True)
    return phase("ownership", "Permissions", [chown])


def _ownership_not_fixed(plugin_dir: Path, runtime_user: str) -> dict:
    chown = item(f"chown -R {runtime_user} {plugin_dir.name}", ok=False)
    return phase("ownership", "Permissions", [chown])


def _jinni_not_answering() -> dict[str, str]:
    raise ConnectionRefusedError("the jinni socket is closed")


def _spool_that_fails_to_read(_spooled_upload: object, *_read_size: int) -> NoReturn:
    raise OSError(errno.EIO, "Input/output error")


@pytest.fixture(autouse=True)
def _served_from_the_test_plugin_root(
    plugin_root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", plugin_root)
    monkeypatch.setattr(restore, "fix_ownership", _ownership_fixed)


async def test_a_printer_fault_after_the_write_is_unprocessable_not_a_bad_request(
    plugin_root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(restore, "fix_ownership", _ownership_not_fixed)
    installed(plugin_root)

    response = await restore_from("spoolman", zip_of({SETTINGS: SIGNED_SETTINGS}))

    assert response.status_code == 422
    assert response.json()["detail"].startswith("RuntimeError: ")


async def test_a_jinni_that_does_not_answer_is_unprocessable_with_nothing_written(
    plugin_root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(jinni_client, "paths", _jinni_not_answering)
    plugin_dir = installed(plugin_root)

    response = await restore_from("spoolman", zip_of({SETTINGS: SIGNED_SETTINGS}))

    assert response.status_code == 422
    assert response.json()["detail"].startswith("ConnectionRefusedError: ")
    assert (plugin_dir / SETTINGS).read_bytes() == CHANGED_SETTINGS


async def test_an_upload_the_printer_cannot_read_back_is_unprocessable(
    plugin_root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The upload is spooled by the web server before the route runs, so reading it back is a
    read of the printer's own memory or flash."""
    monkeypatch.setattr(tempfile.SpooledTemporaryFile, "read", _spool_that_fails_to_read)
    plugin_dir = installed(plugin_root)

    response = await restore_from("spoolman", zip_of({SETTINGS: SIGNED_SETTINGS}))

    assert response.status_code == 422
    assert response.json()["detail"].startswith("OSError: ")
    assert (plugin_dir / SETTINGS).read_bytes() == CHANGED_SETTINGS
