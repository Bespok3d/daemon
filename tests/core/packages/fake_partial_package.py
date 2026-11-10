# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A made-up plugin and a package of its next version that carries only the file that changed,
shared by the single and the batched update tests so both check the same left-out file."""
import hashlib
import io
import json
import zipfile
from pathlib import Path

PLUGIN = "spoolman"
KEPT = "files/daemon.bin"
CHANGED = "files/settings.cfg"
KEPT_BYTES = b"the binary the printer already holds"


def entry(path: str, content: bytes) -> dict:
    return {"path": path, "sha256": hashlib.sha256(content).hexdigest(), "mode": "644"}


def manifest(version: str) -> dict:
    return {
        "name": PLUGIN, "version": version,
        "install": {"dirs": [], "symlinks": [], "patches": [], "start": [], "templates": []},
        "files": [entry(KEPT, KEPT_BYTES), entry(CHANGED, f"v{version}\n".encode())],
    }


def partial_package(tmp_path: Path, version: str) -> Path:
    """A package listing both files but carrying only the changed one."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("manifest.json", json.dumps(manifest(version)))
        package.writestr(CHANGED, f"v{version}\n")
    package_path = tmp_path / f"{PLUGIN}-{version}.b3"
    package_path.write_bytes(buffer.getvalue())
    return package_path


def installed(plugin_root: Path, kept_bytes: bytes) -> Path:
    """The plugin as an earlier install left it, with an unlisted file of its own beside it."""
    plugin_dir = plugin_root / PLUGIN
    (plugin_dir / "files").mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest("1.0")))
    (plugin_dir / KEPT).write_bytes(kept_bytes)
    (plugin_dir / CHANGED).write_text("v1.0\n")
    (plugin_dir / "user_vars.json").write_text('{"port": "7912"}')
    return plugin_dir
