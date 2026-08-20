# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The automatic safety net cannot refuse, so it says who else it took off.

Switching a plugin off strands every installed plugin that needs it. On the path a person drives the
daemon refuses; the net has no such choice, because the printer has to come back up. So it takes the
dependents off in the same sweep and names every one of them in what it reports, leaving no plugin
that stopped working for a reason the user cannot see.
"""
import json
from pathlib import Path

import pytest

from core.packages.deactivation import DEACTIVATED_MARKER
from core.packages.recovery import restart
from core.safety import AttributionIndex, FailureEvidence, OperationContext, OperationKind
from core.safety.decision import Decision
from protocol import DeviceHealth, FailureSignals, ServiceHealth

FEEDER = "filament-feeder"
FEED_SERVICE = "filament-feed"
SPOOL_TRACKER = "spool-tracker"
KLIPPER_SERVICE = "klipper"


def _printer_down() -> FailureEvidence:
    return FailureEvidence(
        health=DeviceHealth(
            services={KLIPPER_SERVICE: ServiceHealth(ready=False, detail="")},
            diagnosis="", signals=FailureSignals(),
        ),
        index=AttributionIndex(by_path={}, by_module={}, by_section={}),
    )


def _install(plugin_root: Path, plugin_id: str, manifest: dict) -> None:
    plugin_dir = plugin_root / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(json.dumps({"name": plugin_id, **manifest}))


def _recover_blaming_the_feeder(plugin_root: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    def blame_the_feeder(evidence: FailureEvidence, ctx: OperationContext,
                         already: list[str] | None = None) -> Decision:
        culprit = None if FEEDER in (already or []) else FEEDER
        return Decision(culprit=culprit, signal="klipper down", fixer="stub")

    def still_down(root: Path, plugin_vars: dict[str, str]) -> FailureEvidence:
        return _printer_down()

    monkeypatch.setattr(restart, "decide", blame_the_feeder)
    monkeypatch.setattr(restart, "gather_evidence", still_down)
    monkeypatch.setattr(restart, "run_restart_batch", lambda commands: None)
    ctx = restart.op_context(OperationKind.INSTALL, {"name": FEEDER})
    return restart._auto_recover(plugin_root, ["restart klipper"], {}, ctx, _printer_down())


def test_the_net_takes_the_dependents_off_with_the_plugin_they_need(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plugin_root = tmp_path / "plugins"
    _install(plugin_root, FEEDER, {"provides": [FEED_SERVICE]})
    _install(plugin_root, SPOOL_TRACKER, {"require": [{"service": FEED_SERVICE}]})

    result = _recover_blaming_the_feeder(plugin_root, monkeypatch)

    assert (plugin_root / SPOOL_TRACKER / DEACTIVATED_MARKER).exists()
    assert SPOOL_TRACKER in result["auto_deactivated"]
    assert FEEDER in result["auto_deactivated"]
