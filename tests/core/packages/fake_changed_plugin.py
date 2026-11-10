# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A made-up installed plugin whose listed files were changed on the printer, shared by the restore
tests so the refusals and the failures put back the same files."""
import hashlib
import io
import zipfile
from pathlib import Path

from core.packages import restore

BINARY = "files/daemon.bin"
SETTINGS = "files/settings.cfg"
RENDERED = "files/rendered.cfg"
SIGNED_BINARY = b"the signed binary"
SIGNED_SETTINGS = b"port = 7912\n"
CHANGED_BINARY = b"a binary someone changed"
CHANGED_SETTINGS = b"port = 1\n"
USER_RENDERED = b"port = 7912 as the user set it\n"


def _entry(path: str, content: bytes) -> dict:
    return {"path": path, "sha256": hashlib.sha256(content).hexdigest(), "mode": "644"}


INSTALLED_MANIFEST = {
    "name": "spoolman", "version": "1.0",
    "install": {"templates": [{"from": "files/rendered.cfg.tmpl", "to": RENDERED}]},
    "files": [
        _entry(BINARY, SIGNED_BINARY),
        _entry(SETTINGS, SIGNED_SETTINGS),
        _entry(RENDERED, b"the placeholder the template renders over"),
    ],
}


def installed(plugin_root: Path) -> Path:
    """The plugin with its three listed files changed on the printer since install."""
    plugin_dir = plugin_root / "spoolman"
    (plugin_dir / "files").mkdir(parents=True)
    (plugin_dir / BINARY).write_bytes(CHANGED_BINARY)
    (plugin_dir / SETTINGS).write_bytes(CHANGED_SETTINGS)
    (plugin_dir / RENDERED).write_bytes(USER_RENDERED)
    return plugin_dir


def zip_of(tmp_path: Path, members: dict[str, bytes]) -> Path:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as restore_zip:
        for name, content in members.items():
            restore_zip.writestr(name, content)
    archive_path = tmp_path / "restore.zip"
    archive_path.write_bytes(buffer.getvalue())
    return archive_path


def restore_from(plugin_dir: Path, archive_path: Path) -> list[str]:
    with archive_path.open("rb") as restore_archive:
        return restore.restore_files(plugin_dir, INSTALLED_MANIFEST, restore_archive, "")
