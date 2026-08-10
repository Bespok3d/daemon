# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The published package must never advertise a version the running daemon does not report.

manifest.json is what the app and the printer read to decide whether a newer daemon exists;
DAEMON_VERSION is what a running daemon answers with on /health. A release built from a tree where
those two disagree ships a package that lies about itself, so the gate refuses the mismatch here
(the guard used to live in the pack script, which no longer exists: b3-builder packs the daemon).
"""

import json
from pathlib import Path

from version import DAEMON_VERSION, MIN_JINNI_VERSION

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_manifest_version_matches_the_running_daemon_version() -> None:
    manifest = json.loads((REPO_ROOT / "manifest.json").read_text())

    assert manifest["version"] == DAEMON_VERSION, "bump manifest.json and version.py together"


def test_manifest_declares_the_jinni_floor_the_running_daemon_enforces() -> None:
    """The app refuses a daemon whose jinni floor this printer misses, and it reads that floor off
    the published package rather than off a printer it has not installed yet. A manifest that omits
    the floor, or carries a stale one, lets a daemon reach a printer whose jinni it will then refuse
    to drive, leaving the printer enrolled but unmanageable.
    """
    manifest = json.loads((REPO_ROOT / "manifest.json").read_text())

    assert manifest["min_jinni_version"] == MIN_JINNI_VERSION, (
        "bump manifest.json and version.py together"
    )
