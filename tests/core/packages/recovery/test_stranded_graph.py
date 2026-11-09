# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Who the dependency graph says is stranded, and the order they go off in: a plugin always before
the stranded plugin it needs, as every other switch-off does."""
import json
from pathlib import Path

import pytest

from core.packages.deactivation import DEACTIVATED_MARKER
from core.packages.machinery import MACHINERY_PACKAGES
from core.packages.recovery import stranded
from core.packages.recovery.stranded import stranded_plugins


def _install(plugin_root: Path, plugin_id: str, manifest: dict, switched_off: bool = False) -> None:
    plugin_dir = plugin_root / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(json.dumps({"name": plugin_id, **manifest}))
    if switched_off:
        (plugin_dir / DEACTIVATED_MARKER).write_text(json.dumps({"reason": "install phase failed"}))


def test_stranded_plugins_follow_the_chain_and_name_what_each_lost() -> None:
    manifests: dict[str, dict] = {
        "base": {"provides": ["svc-base"]},
        "middle": {"provides": ["svc-middle"], "require": [{"service": "svc-base"}]},
        "leaf": {"require": [{"service": "svc-middle"}]},
    }
    assert stranded_plugins(manifests, frozenset({"base"})) == {
        "middle": ["svc-base"], "leaf": ["svc-middle"],
    }


def test_a_service_nothing_installed_provides_strands_nobody() -> None:
    manifests: dict[str, dict] = {"orphan": {"require": [{"service": "never-installed"}]}}
    assert stranded_plugins(manifests, frozenset()) == {}


def test_a_service_another_plugin_still_provides_strands_nobody() -> None:
    manifests: dict[str, dict] = {
        "first-provider": {"provides": ["shared"]},
        "second-provider": {"provides": ["shared"]},
        "consumer": {"require": [{"service": "shared"}]},
    }
    assert stranded_plugins(manifests, frozenset({"first-provider"})) == {}


def test_a_plugin_that_needs_stranded_machinery_stays_on_as_the_machinery_does() -> None:
    machinery_id = sorted(MACHINERY_PACKAGES)[0]
    manifests: dict[str, dict] = {
        "base": {"provides": ["svc-base"]},
        machinery_id: {"provides": ["svc-machinery"], "require": [{"service": "svc-base"}]},
        "leaf": {"require": [{"service": "svc-machinery"}]},
    }
    assert stranded_plugins(manifests, frozenset({"base"})) == {machinery_id: ["svc-base"]}


def test_a_plugin_goes_off_before_the_stranded_plugin_it_needs(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plugin_root = tmp_path / "plugins"
    _install(plugin_root, "base", {"provides": ["svc-base"]}, switched_off=True)
    _install(plugin_root, "middle", {"provides": ["svc-middle"],
                                     "require": [{"service": "svc-base"}]})
    _install(plugin_root, "leaf", {"require": [{"service": "svc-base"}, {"service": "svc-middle"}]})
    order: list[str] = []
    monkeypatch.setattr(stranded, "deactivate_plugin",
                        lambda plugin_dir, _vars, _why: order.append(plugin_dir.name))

    switched_off = stranded.switch_off_stranded(plugin_root, {})
    assert list(switched_off) == ["leaf", "middle"] == order
    assert switched_off["middle"] == ["svc-base"]
