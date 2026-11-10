# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""An installed plugin with one listed file changed on the printer, and the two plugin-file routes
called the way the app calls them, shared by the hashes and the restore route tests."""
import hashlib
import io
import json
import zipfile
from pathlib import Path

import httpx

from api import app
from tests.fake_owner import ISSUED_TOKEN

SETTINGS = "files/settings.cfg"
SIGNED_SETTINGS = b"port = 7912\n"
CHANGED_SETTINGS = b"port = 1\n"


def installed(plugin_root: Path) -> Path:
    plugin_dir = plugin_root / "spoolman"
    (plugin_dir / "files").mkdir(parents=True)
    (plugin_dir / SETTINGS).write_bytes(CHANGED_SETTINGS)
    signed_entry = {"path": SETTINGS, "sha256": hashlib.sha256(SIGNED_SETTINGS).hexdigest()}
    manifest = {"name": "spoolman", "version": "1.0", "files": [signed_entry]}
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest))
    return plugin_dir


def zip_of(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as restore_zip:
        for name, content in members.items():
            restore_zip.writestr(name, content)
    return buffer.getvalue()


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
        headers={"Authorization": f"Bearer {ISSUED_TOKEN}"},
    )


async def hashes_of(plugin_id: str) -> httpx.Response:
    async with _client() as client:
        return await client.get(f"/plugins/{plugin_id}/file-hashes")


async def restore_from(plugin_id: str, restore_zip: bytes) -> httpx.Response:
    async with _client() as client:
        upload = {"file": ("restore.zip", restore_zip, "application/zip")}
        return await client.post(f"/plugins/{plugin_id}/restore-files", files=upload)
