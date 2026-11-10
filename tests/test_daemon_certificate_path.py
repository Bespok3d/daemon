# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The TLS certificate the daemon serves follows the data root, on every printer.

The daemon is generic: where Bespok3d keeps its tree is the printer's own fact and is declared in
one place (core.data_root.DATA_ROOT, overridable with BESPOK3D_DATA_ROOT). daemon.py used to write
the Snapmaker U1's /userdata/bespok3d out in full, so on a printer that keeps the tree anywhere else
(a Klipper host, where it lives in the login user's home) the daemon found no certificate and served
plain HTTP, which the app refuses because it pins the cert. The module-level paths are computed at
import, so these tests point the environment at a throwaway root and import the module there.
"""

import importlib
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

import api
from core import data_root

CERTIFICATE_RELATIVE = "etc/daemon/server.crt"
KEY_RELATIVE = "etc/daemon/server.key"


@pytest.fixture
def daemon_rooted_at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    """daemon.py imported against a throwaway data root, with the session's modules put back after.

    Both modules are reloaded: core.data_root reads the environment at import, and daemon.py derives
    its two paths from it at import. Restoring them on the way out matters because every other suite
    in this run shares those module objects.
    """
    monkeypatch.setenv("BESPOK3D_DATA_ROOT", str(tmp_path))
    importlib.reload(data_root)

    yield importlib.reload(importlib.import_module("daemon"))

    monkeypatch.undo()
    importlib.reload(data_root)
    importlib.reload(importlib.import_module("daemon"))


def test_the_certificate_and_key_sit_under_the_data_root(
    daemon_rooted_at: ModuleType, tmp_path: Path
) -> None:
    assert daemon_rooted_at.CERT_FILE == tmp_path / CERTIFICATE_RELATIVE
    assert daemon_rooted_at.KEY_FILE == tmp_path / KEY_RELATIVE


def test_a_certificate_under_that_root_is_the_one_uvicorn_serves(
    daemon_rooted_at: ModuleType, tmp_path: Path
) -> None:
    """The pair only reaches uvicorn when both files are found where the root says they are, so a
    root the daemon does not follow is a printer that quietly answers over plain HTTP."""
    certificate = tmp_path / CERTIFICATE_RELATIVE
    key = tmp_path / KEY_RELATIVE
    certificate.parent.mkdir(parents=True)
    certificate.write_text("PLACEHOLDER certificate, not a real one")
    key.write_text("PLACEHOLDER key, not a real one")

    assert daemon_rooted_at._ssl_kwargs() == {
        "ssl_certfile": str(certificate),
        "ssl_keyfile": str(key),
    }


def test_no_certificate_under_that_root_leaves_uvicorn_unencrypted(
    daemon_rooted_at: ModuleType,
) -> None:
    assert daemon_rooted_at._ssl_kwargs() == {}


def test_the_api_probes_the_same_certificate_path() -> None:
    """api decides whether it is running on a printer, and so whether to hide /docs and spawn the
    jinni, by whether that certificate exists. It has to look at the file daemon.py serves. Other
    suites import api long before this one runs, so the check is that the path is anchored to the
    root rather than written out, not that a re-import picks a temporary root up.
    """
    assert api._CERT_FILE == data_root.DATA_ROOT / CERTIFICATE_RELATIVE
