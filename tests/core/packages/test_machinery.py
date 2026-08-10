# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The name the daemon knows itself by is the name it is published under.

If the two ever drift, the machinery guard stops recognising the daemon and the safety net becomes
free to take it off a printer, so this reads the published manifest rather than trusting a copy.
"""
import json
from pathlib import Path

from core.packages.machinery import DAEMON_PACKAGE, is_machinery

MANIFEST = Path(__file__).resolve().parents[3] / "manifest.json"


def test_the_daemon_package_name_matches_the_published_manifest() -> None:
    assert json.loads(MANIFEST.read_text())["name"] == DAEMON_PACKAGE


def test_an_ordinary_plugin_is_not_machinery() -> None:
    assert is_machinery("spoolman") is False
