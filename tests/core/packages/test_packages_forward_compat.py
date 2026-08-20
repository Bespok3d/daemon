# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A manifest written for a newer daemon still works on this one.

Packages on the store outlive the daemon build that reads them: a later release adds a manifest key
(a version pin on a requirement is the one already coming), and printers that have not taken the
daemon update yet must keep installing those packages instead of failing on a word they do not know.
So an unrecognised key is ignored, never a refusal, and what this daemon does understand it still
acts on.
"""

import json
from pathlib import Path

from core.intent import normalize_install
from core.packages import dependencies


def _provider_on_the_printer(plugin_root: Path, plugin_id: str, service: str) -> None:
    plugin_dir = plugin_root / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(
        json.dumps({"name": plugin_id, "provides": [service]}))


def test_an_unknown_key_on_a_requirement_does_not_hide_the_service_it_names(
        tmp_path: Path) -> None:
    versioned = {
        "name": "spool-tracker",
        "require": [{"service": "filament-feed", "min_version": "1.4.0", "why": "reads the lane"}],
    }

    assert dependencies.unsatisfied_requirements(tmp_path, "spool-tracker", versioned) == [
        "filament-feed"]

    _provider_on_the_printer(tmp_path, "filament-feeder", "filament-feed")

    assert dependencies.unsatisfied_requirements(tmp_path, "spool-tracker", versioned) == []


def test_an_unknown_key_on_a_provided_service_still_provides_it(tmp_path: Path) -> None:
    provider_dir = tmp_path / "filament-feeder"
    provider_dir.mkdir(parents=True)
    (provider_dir / "manifest.json").write_text(json.dumps({
        "name": "filament-feeder",
        "provides": [{"service": "filament-feed", "version": "2.0.0"}],
    }))

    assert dependencies.services_the_printer_can_serve(tmp_path, frozenset()) >= {"filament-feed"}


def test_an_unknown_install_section_is_ignored_and_the_known_ones_still_run() -> None:
    ops = normalize_install({
        "dirs": ["etc/spool-tracker"],
        "future_section": [{"anything": "at all"}],
        "restart": ["klipper"],
    })

    assert ops["dirs"] == ["etc/spool-tracker"]
    assert ops["start"] == ["/etc/init.d/S60klipper restart"]
