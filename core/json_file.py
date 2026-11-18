# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Small state files the daemon keeps as JSON under its data root."""
import json
import os
from pathlib import Path


def read_json(path: Path) -> object | None:
    """The value the file holds, or None when it cannot be read as JSON: a file torn by a power cut
    or edited by hand must never stop the daemon."""
    try:
        stored: object = json.loads(path.read_text())
        return stored
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def write_json(path: Path, value: object) -> None:
    """Written whole or not at all, and on the flash when this returns: a power cut may follow at
    once. The directory is synced too, or the rename itself may not survive the power cut. A failed
    write leaves the old file and no staging copy on a flash that may already be full."""
    serialized = json.dumps(value, indent=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_suffix(".tmp")
    try:
        _stage(staging, serialized)
        os.replace(staging, path)
    except OSError:
        staging.unlink(missing_ok=True)
        raise
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _stage(staging: Path, serialized: str) -> None:
    with staging.open("w") as staged:
        staged.write(serialized)
        staged.flush()
        os.fsync(staged.fileno())
