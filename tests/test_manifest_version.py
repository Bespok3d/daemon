"""The published package must never advertise a version the running daemon does not report.

manifest.json is what the app and the printer read to decide whether a newer daemon exists;
DAEMON_VERSION is what a running daemon answers with on /health. A release built from a tree where
those two disagree ships a package that lies about itself, so the gate refuses the mismatch here
(the guard used to live in the pack script, which no longer exists: b3-builder packs the daemon).
"""

import json
from pathlib import Path

from version import DAEMON_VERSION

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_manifest_version_matches_the_running_daemon_version() -> None:
    manifest = json.loads((REPO_ROOT / "manifest.json").read_text())

    assert manifest["version"] == DAEMON_VERSION, "bump manifest.json and version.py together"
