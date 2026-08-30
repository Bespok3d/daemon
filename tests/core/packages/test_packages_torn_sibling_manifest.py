# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""One plugin whose manifest.json was half written by a power cut used to stop every install and
every update on the printer, because the pre-flight read every installed manifest through an
unguarded json.loads. A torn manifest now declares no service, declares no conflict, orders
nowhere and has no log, so the plugin next to it still installs."""

import json
from pathlib import Path

import pytest

from api.routes import feeds as routes_feeds
from api.schemas import ManifestWarning, PackResultsResponse
from core import jinni_client, packages
from core.packages import dependencies, install_refusals
from core.packages.recovery import evidence
from tests.core.packages.fake_panel_printer import (
    BASE_LAYER,
    hand_over,
    install_panel_patcher,
    kept_panel,
)

TORN_MANIFEST_TEXT = '{"name": "camera", "version": "0.1.6", "prov'


def _installed_plugin(plugin_root: Path, plugin_id: str, manifest: dict) -> Path:
    plugin_dir = plugin_root / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest))
    return plugin_dir


def _plugin_with_a_torn_manifest(plugin_root: Path, plugin_id: str) -> Path:
    plugin_dir = plugin_root / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(TORN_MANIFEST_TEXT)
    return plugin_dir


def test_a_torn_sibling_manifest_does_not_stop_an_unrelated_install(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugins"
    _plugin_with_a_torn_manifest(plugin_root, "camera")
    _installed_plugin(plugin_root, "spoolman", {"name": "spoolman", "provides": ["spool-tracking"]})
    arriving = {"name": "rfid-ntag", "require": [{"service": "spool-tracking"}]}
    arriving_dir = _installed_plugin(plugin_root, "rfid-ntag", arriving)

    install_refusals.refuse_unmet_dependencies(plugin_root, arriving_dir, "rfid-ntag", arriving)

    assert arriving_dir.exists()


def test_a_torn_manifest_declares_no_service(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugins"
    _plugin_with_a_torn_manifest(plugin_root, "camera")
    _installed_plugin(plugin_root, "spoolman", {"name": "spoolman", "provides": ["spool-tracking"]})

    servable = dependencies.services_the_printer_can_serve(plugin_root, frozenset())

    assert "spool-tracking" in servable


def test_a_torn_manifest_declares_no_conflict(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugins"
    _plugin_with_a_torn_manifest(plugin_root, "camera")

    assert dependencies.installed_conflicts(plugin_root, "rfid-ntag", {}) == []


def test_a_torn_manifest_orders_nowhere_and_the_rest_still_order(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugins"
    torn_dir = _plugin_with_a_torn_manifest(plugin_root, "camera")
    provider_dir = _installed_plugin(
        plugin_root, "spoolman", {"name": "spoolman", "provides": ["spool-tracking"]},
    )
    dependent_dir = _installed_plugin(
        plugin_root, "rfid-ntag",
        {"name": "rfid-ntag", "require": [{"service": "spool-tracking"}]},
    )

    ordered = dependencies.topo_sort([dependent_dir, torn_dir, provider_dir])

    assert set(ordered) == {dependent_dir, torn_dir, provider_dir}
    assert ordered.index(provider_dir) < ordered.index(dependent_dir)


def test_a_torn_manifest_has_no_log_to_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin_root = tmp_path / "plugins"
    _plugin_with_a_torn_manifest(plugin_root, "camera")
    monkeypatch.setattr(packages, "PLUGIN_ROOT", plugin_root)

    assert routes_feeds._plugin_log_source("camera", "") is None


def test_a_torn_neighbour_stops_a_patched_file_being_taken_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The plugin holding a file's true original may be the very plugin whose manifest is torn, so
    the take-over stops and says which plugin it cannot read, instead of adopting the live file and
    baking somebody else's changes in as the original forever."""
    monkeypatch.setattr(jinni_client, "variant_facts", dict)
    plugin_root = tmp_path / "plugins"
    _plugin_with_a_torn_manifest(plugin_root, "camera")
    adopter_dir = install_panel_patcher(plugin_root, BASE_LAYER, kept_copy=None)

    adoption = hand_over(plugin_root, adopter_dir)

    assert adoption["ok"] is False
    assert "camera" in adoption["label"]
    assert not kept_panel(adopter_dir).exists()


def test_a_torn_manifest_is_left_out_of_the_evidence_and_every_other_plugin_is_indexed(
    tmp_path: Path,
) -> None:
    """A plugin nobody can read placed nothing anybody can attribute, so the post-restart evidence
    goes past it and still names the plugin behind a failure the other plugins placed."""
    plugin_root = tmp_path / "plugins"
    _plugin_with_a_torn_manifest(plugin_root, "camera")
    _installed_plugin(plugin_root, "spoolman", {
        "name": "spoolman",
        "install": {"place": [{"class": "klipper-extra", "src": "files/spoolman.py"}]},
    })

    index = evidence._build_attribution_index(
        plugin_root, {"KLIPPER_EXTRAS": "/home/lava/klipper/klippy/extras"}, {},
    )

    assert index.by_module["spoolman"] == "spoolman"
    assert index.by_path["/home/lava/klipper/klippy/extras/spoolman.py"] == "spoolman"
    assert "camera" not in {*index.by_path.values(), *index.by_module.values()}


def test_the_answer_carries_the_torn_plugin_the_operation_went_past(tmp_path: Path) -> None:
    """Going past a torn plugin in silence is what left the user with a plugin that quietly does
    nothing, so the operation's own answer names it and says what could not be read."""
    plugin_root = tmp_path / "plugins"
    _plugin_with_a_torn_manifest(plugin_root, "camera")

    with packages.collecting_torn_plugins() as torn:
        dependencies.services_the_printer_can_serve(plugin_root, frozenset())
    answer = PackResultsResponse(
        ok=True,
        results=[],
        manifest_warnings=[ManifestWarning(**warning)
                           for warning in packages.torn_plugin_warnings(torn)],
    ).model_dump(mode="json")

    assert [warning["plugin"] for warning in answer["manifest_warnings"]] == ["camera"]
    assert answer["manifest_warnings"][0]["problem"] == "manifest-unreadable"
    assert answer["manifest_warnings"][0]["detail"]


def test_a_torn_manifest_met_outside_an_operation_lands_in_nobodys_answer(tmp_path: Path) -> None:
    """Tailing one plugin's log or guarding a print reads a manifest for its own reasons. What
    those reads meet must never turn up in the next install's answer as a plugin it went past."""
    plugin_root = tmp_path / "plugins"
    torn_dir = _plugin_with_a_torn_manifest(plugin_root, "camera")
    packages.readable_manifest(torn_dir)

    with packages.collecting_torn_plugins() as torn:
        pass

    assert packages.torn_plugin_warnings(torn) == []
