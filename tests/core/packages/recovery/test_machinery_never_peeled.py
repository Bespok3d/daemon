# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""No automatic step takes the printer's own machinery off the printer.

The safety net deactivates a plugin that breaks Klipper so the printer keeps working. Handed the
daemon or the jinni as the culprit it must do nothing: an enrolled printer whose daemon was taken
off it can no longer be managed at all, which is the very outcome the net exists to prevent. It must
also leave nothing behind for a name that was never an installed plugin.
"""
import json
from pathlib import Path

import pytest

from core.packages.deactivation import DEACTIVATED_MARKER
from core.packages.machinery import DAEMON_PACKAGE
from core.packages.recovery import restart
from core.safety import AttributionIndex, FailureEvidence, OperationContext, OperationKind
from core.safety.decision import Decision
from protocol import DeviceHealth, FailureSignals, ServiceHealth

JINNI_PACKAGE = "bespok3d-jinni-snapmaker-u1"
PLUGIN = "spoolman"
KLIPPER_SERVICE = "klipper"


def _printer_down() -> FailureEvidence:
    return FailureEvidence(
        health=DeviceHealth(
            services={KLIPPER_SERVICE: ServiceHealth(ready=False, detail="")},
            diagnosis="", signals=FailureSignals(),
        ),
        index=AttributionIndex(by_path={}, by_module={}, by_section={}),
    )


def _plugin_root(tmp_path: Path, installed: list[str]) -> Path:
    root = tmp_path / "plugins"
    for name in installed:
        (root / name).mkdir(parents=True)
        (root / name / "manifest.json").write_text(json.dumps({"name": name}))

    return root


def _peeled_by_the_safety_net(monkeypatch: pytest.MonkeyPatch, plugin_root: Path,
                              blamed: list[str]) -> list[str]:
    """Run one auto-recovery in which the fixer chain blames each of `blamed` in turn, and report
    which plugins it actually took off the printer."""
    peeled: list[str] = []

    def blame_in_turn(evidence: FailureEvidence, ctx: OperationContext,
                      already: list[str] | None = None) -> Decision:
        left = [name for name in blamed if name not in (already or [])]

        return Decision(culprit=left[0] if left else None, signal="klipper down", fixer="stub")

    def record(plugin_dir: Path, plugin_vars: dict[str, str], reason: str) -> None:
        peeled.append(plugin_dir.name)

    def still_down(root: Path, plugin_vars: dict[str, str]) -> FailureEvidence:
        return _printer_down()

    monkeypatch.setattr(restart, "decide", blame_in_turn)
    monkeypatch.setattr(restart, "deactivate_plugin", record)
    monkeypatch.setattr(restart, "gather_evidence", still_down)
    monkeypatch.setattr(restart, "run_restart_batch", lambda commands: None)
    ctx = restart.op_context(OperationKind.INSTALL, {"name": PLUGIN})
    restart._auto_recover(plugin_root, ["restart klipper"], {}, ctx, _printer_down())

    return peeled


def test_the_daemon_is_passed_over_and_the_plugin_is_deactivated(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plugin_root = _plugin_root(tmp_path, [PLUGIN])

    peeled = _peeled_by_the_safety_net(monkeypatch, plugin_root, [DAEMON_PACKAGE, PLUGIN])

    assert peeled == [PLUGIN]


def test_the_jinni_is_passed_over_and_the_plugin_is_deactivated(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plugin_root = _plugin_root(tmp_path, [PLUGIN])

    peeled = _peeled_by_the_safety_net(monkeypatch, plugin_root, [JINNI_PACKAGE, PLUGIN])

    assert peeled == [PLUGIN]


def test_a_blamed_name_that_is_not_an_installed_plugin_leaves_nothing_behind(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plugin_root = _plugin_root(tmp_path, [PLUGIN])

    peeled = _peeled_by_the_safety_net(monkeypatch, plugin_root, [DAEMON_PACKAGE, JINNI_PACKAGE])

    assert peeled == []
    assert list(plugin_root.rglob(DEACTIVATED_MARKER)) == []
