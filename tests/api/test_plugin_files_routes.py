# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The hashes of an installed plugin's kept files at the HTTP boundary the app calls, and how both
plugin-file routes answer for a plugin that is not installed."""
import hashlib
import json
from pathlib import Path

import pytest

from core import packages
from core.packages.integrity import ESCAPING_PLUGIN_ID, IntegrityError
from tests.api.fake_spoolman_files import (
    CHANGED_SETTINGS,
    SETTINGS,
    SIGNED_SETTINGS,
    hashes_of,
    installed,
    restore_from,
    zip_of,
)

pytestmark = pytest.mark.usefixtures("daemon_acl")


@pytest.fixture(autouse=True)
def _served_from_the_test_plugin_root(
    plugin_root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", plugin_root)


async def test_the_hashes_of_the_kept_files_are_answered(plugin_root: Path) -> None:
    installed(plugin_root)

    response = await hashes_of("spoolman")

    assert response.status_code == 200
    assert response.json() == {"files": {SETTINGS: hashlib.sha256(CHANGED_SETTINGS).hexdigest()}}


async def test_a_plugin_that_is_not_there_has_no_hashes() -> None:
    response = await hashes_of("spoolman")

    assert (response.status_code, response.json()) == (404, {"detail": "spoolman"})


async def test_a_plugin_dir_without_a_manifest_is_not_installed(plugin_root: Path) -> None:
    (installed(plugin_root) / "manifest.json").unlink()

    assert (await hashes_of("spoolman")).status_code == 404
    assert (await restore_from("spoolman", zip_of({}))).status_code == 404


@pytest.mark.parametrize("broken_manifest", ['{"name": "spool', '["spoolman"]'])
async def test_a_plugin_dir_with_a_broken_manifest_is_not_installed(
    plugin_root: Path, broken_manifest: str,
) -> None:
    (installed(plugin_root) / "manifest.json").write_text(broken_manifest)

    assert (await hashes_of("spoolman")).status_code == 404
    assert (await restore_from("spoolman", zip_of({}))).status_code == 404


def _refused_as_escaping(_plugin_root: Path, plugin_id: str) -> Path:
    raise IntegrityError(plugin_id, ESCAPING_PLUGIN_ID, [plugin_id])


async def test_an_id_that_leaves_the_plugin_root_is_an_integrity_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """httpx folds `..` out of a URL before it is sent, so the lookup refuses a plain id here the
    way it refuses the `..` a raw client gets through."""
    monkeypatch.setattr(packages, "contained_plugin_dir", _refused_as_escaping)
    refusal = {
        "error": "integrity", "plugin_id": "spoolman", "reason": ESCAPING_PLUGIN_ID,
        "paths": ["spoolman"],
    }

    for response in [await hashes_of("spoolman"), await restore_from("spoolman", zip_of({}))]:
        assert (response.status_code, response.json()["detail"]) == (409, refusal)


async def test_an_installed_manifest_the_printer_cannot_resolve_is_unprocessable(
    plugin_root: Path,
) -> None:
    """The app sent nothing wrong, so neither route may answer as if it had."""
    manifest_path = installed(plugin_root) / "manifest.json"
    unresolvable_install: dict[str, list[dict]] = {"place": [{"variants": []}]}
    manifest = {**json.loads(manifest_path.read_text()), "install": unresolvable_install}
    manifest_path.write_text(json.dumps(manifest))

    hashes_answer = await hashes_of("spoolman")
    restore_answer = await restore_from("spoolman", zip_of({SETTINGS: SIGNED_SETTINGS}))

    assert hashes_answer.status_code == restore_answer.status_code == 422
    assert restore_answer.json()["detail"] == hashes_answer.json()["detail"]
