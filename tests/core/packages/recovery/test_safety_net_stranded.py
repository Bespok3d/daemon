# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A plugin left on while a plugin it needs is off is taken off in one round, not one per restart.

Klipper names only the first config section it cannot load, so a net that waits for the printer to
name each stranded plugin restarts once per plugin. On a printer whose RFID base was switched off
that was ten rounds and close to ten minutes. The dependency graph already says who is stranded.
"""
import json
from pathlib import Path

import pytest

from core.packages.deactivation import DEACTIVATED_MARKER
from core.packages.recovery import restart
from core.safety import AttributionIndex, FailureEvidence, OperationContext, OperationKind
from core.safety.decision import Decision
from protocol import DeviceHealth, FailureSignals, ServiceHealth

READER_BASE = "reader-base"
DETECT_BASE = "detect-base"
TAG_READER = "tag-reader"
TAG_SERVICE = "tag-service"
TAG_CONSUMERS = ["lane-feeder", "brand-a-tags", "brand-b-tags", "brand-c-tags"]
KLIPPER_SERVICE = "klipper"


def _evidence(klipper_ready: bool) -> FailureEvidence:
    return FailureEvidence(
        health=DeviceHealth(
            services={KLIPPER_SERVICE: ServiceHealth(ready=klipper_ready, detail="")},
            diagnosis="", signals=FailureSignals(),
        ),
        index=AttributionIndex(by_path={}, by_module={}, by_section={}),
    )


def _install(plugin_root: Path, plugin_id: str, manifest: dict, switched_off: bool = False) -> None:
    plugin_dir = plugin_root / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(json.dumps({"name": plugin_id, **manifest}))
    if switched_off:
        (plugin_dir / DEACTIVATED_MARKER).write_text(json.dumps({"reason": "install phase failed"}))


def _install_tag_stack_with_its_base_off(plugin_root: Path) -> None:
    _install(plugin_root, READER_BASE, {"provides": [READER_BASE]}, switched_off=True)
    _install(plugin_root, DETECT_BASE, {"provides": [DETECT_BASE]}, switched_off=True)
    _install(plugin_root, TAG_READER, {
        "provides": [TAG_SERVICE],
        "require": [{"service": READER_BASE}, {"service": DETECT_BASE}],
    })
    for consumer in TAG_CONSUMERS:
        _install(plugin_root, consumer, {"require": [{"service": TAG_SERVICE}]})


def _still_on(plugin_root: Path) -> list[str]:
    return [plugin_id for plugin_id in [*TAG_CONSUMERS, TAG_READER]
            if not (plugin_root / plugin_id / DEACTIVATED_MARKER).exists()]


def _recover_like_klipper(plugin_root: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[dict, int]:
    """Klipper's view: down while any stranded plugin is still on, naming only the first of them."""
    restarts: list[list[str]] = []

    def first_bad_section(evidence: FailureEvidence, ctx: OperationContext,
                          already: list[str] | None = None) -> Decision:
        still_on = _still_on(plugin_root)
        culprit = still_on[0] if still_on else None
        return Decision(culprit=culprit, signal="section failed", fixer="stub")

    def klipper_now(root: Path, plugin_vars: dict[str, str]) -> FailureEvidence:
        return _evidence(klipper_ready=not _still_on(plugin_root))

    monkeypatch.setattr(restart, "decide", first_bad_section)
    monkeypatch.setattr(restart, "gather_evidence", klipper_now)
    monkeypatch.setattr(restart, "run_restart_batch", restarts.append)
    ctx = restart.op_context(OperationKind.RECONFIGURE, {"name": "idle-timeout"})
    result = restart._auto_recover(plugin_root, ["restart klipper"], {}, ctx, _evidence(False))
    return result, len(restarts)


def test_every_stranded_plugin_goes_off_in_one_restart(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plugin_root = tmp_path / "plugins"
    _install_tag_stack_with_its_base_off(plugin_root)

    result, restarts = _recover_like_klipper(plugin_root, monkeypatch)

    assert restarts == 1
    assert result["ok"]
    assert _still_on(plugin_root) == []
    tag_reader_marker = json.loads((plugin_root / TAG_READER / DEACTIVATED_MARKER).read_text())
    assert "dependency not satisfied" in tag_reader_marker["reason"]


def test_a_chain_below_the_blamed_plugin_goes_off_in_the_same_restart(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plugin_root = tmp_path / "plugins"
    _install(plugin_root, TAG_READER, {"provides": [TAG_SERVICE]})
    _install(plugin_root, "lane-feeder", {"provides": ["lanes"],
                                          "require": [{"service": TAG_SERVICE}]})
    _install(plugin_root, "lane-display", {"require": [{"service": "lanes"}]})
    restarts: list[list[str]] = []

    def blame_the_tag_reader(evidence: FailureEvidence, ctx: OperationContext,
                             already: list[str] | None = None) -> Decision:
        culprit = None if TAG_READER in (already or []) else TAG_READER
        return Decision(culprit=culprit, signal="section failed", fixer="stub")

    monkeypatch.setattr(restart, "decide", blame_the_tag_reader)
    monkeypatch.setattr(restart, "gather_evidence", lambda root, plugin_vars: _evidence(True))
    monkeypatch.setattr(restart, "run_restart_batch", restarts.append)
    ctx = restart.op_context(OperationKind.INSTALL, {"name": TAG_READER})
    result = restart._auto_recover(plugin_root, ["restart klipper"], {}, ctx, _evidence(False))

    assert len(restarts) == 1
    assert (plugin_root / "lane-display" / DEACTIVATED_MARKER).exists()
    assert "lane-display" in result["auto_deactivated"]


def _restart_like_klipper(plugin_root: Path, monkeypatch: pytest.MonkeyPatch,
                          blamed: str | None = None) -> tuple[dict, int]:
    """A core restart on a printer whose Klipper stays down while a stranded plugin, or the plugin
    Klipper names, is still on."""
    restarts: list[list[str]] = []

    def restart_once(deferred_cmds: list[str]) -> dict:
        restarts.append(deferred_cmds)
        return {"plugin_id": "(services)", "ok": True, "skipped": False, "reason": "", "log": []}

    def blamed_still_on() -> bool:
        return blamed is not None and not (plugin_root / blamed / DEACTIVATED_MARKER).exists()

    def name_the_blamed(evidence: FailureEvidence, ctx: OperationContext,
                        already: list[str] | None = None) -> Decision:
        culprit = blamed if blamed_still_on() else None
        return Decision(culprit=culprit, signal="section failed", fixer="stub")

    def klipper_now(root: Path, plugin_vars: dict[str, str]) -> FailureEvidence:
        return _evidence(klipper_ready=not _still_on(plugin_root) and not blamed_still_on())

    monkeypatch.setattr(restart, "touches_core_service", lambda deferred_cmds: True)
    monkeypatch.setattr(restart, "run_restart_batch", restart_once)
    monkeypatch.setattr(restart, "decide", name_the_blamed)
    monkeypatch.setattr(restart, "gather_evidence", klipper_now)
    ctx = restart.op_context(OperationKind.RECOVER, {})
    result = restart.restart_services(plugin_root, ["restart klipper"], {}, ctx)
    return result, len(restarts)


def test_a_core_restart_takes_the_stranded_plugins_off_first_and_restarts_once(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The printer that took ten rounds: its base off, the tag reader and every tag consumer still
    on. All of them go off before the one restart, so the printer comes back without a net round."""
    plugin_root = tmp_path / "plugins"
    _install_tag_stack_with_its_base_off(plugin_root)

    result, restarts = _restart_like_klipper(plugin_root, monkeypatch)

    assert restarts == 1
    assert result["ok"]
    assert _still_on(plugin_root) == []
    assert set(result["auto_deactivated"].split(", ")) == {*TAG_CONSUMERS, TAG_READER}
    assert "dependency not satisfied" in result["fix_detail"]


def test_a_plugin_klipper_names_goes_off_in_one_net_round_next_to_the_stranded_ones(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plugin_root = tmp_path / "plugins"
    _install_tag_stack_with_its_base_off(plugin_root)
    _install(plugin_root, "chamber-fan", {})

    result, restarts = _restart_like_klipper(plugin_root, monkeypatch, blamed="chamber-fan")

    assert restarts == 2
    assert result["ok"]
    switched_off = set(result["auto_deactivated"].split(", "))
    assert switched_off == {*TAG_CONSUMERS, TAG_READER, "chamber-fan"}
    assert "dependency not satisfied" in result["fix_detail"]
    assert "section failed" in result["fix_detail"]
