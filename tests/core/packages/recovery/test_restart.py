"""White-box units for the safety-net driver (core/packages/recovery/restart.py).

Re-export identity guards the public entry points the orchestrator wires; the units exercise the
small pure pieces directly from their home module.
"""
from core import packages
from core.packages.recovery import restart
from core.safety import OperationKind


def test_orchestrator_reexports_the_restart_entry_points() -> None:
    assert packages.op_context is restart.op_context
    assert packages.restart_phases is restart.restart_phases
    assert packages.restart_services is restart.restart_services


def test_op_context_carries_operation_facts() -> None:
    manifest = {"name": "spoolman", "version": "0.1.8", "publisher": "bespok3d"}

    ctx = restart.op_context(OperationKind.INSTALL, manifest)

    assert ctx.kind is OperationKind.INSTALL
    assert ctx.plugin_id == "spoolman"
    assert ctx.plugin_version == "0.1.8"
    assert ctx.publisher == "bespok3d"


def test_touches_core_service_true_for_klipper_restart() -> None:
    assert restart._touches_core_service(["/etc/init.d/S60klipper restart"]) is True


def test_touches_core_service_false_for_plugin_service_bounce() -> None:
    assert restart._touches_core_service(["/etc/init.d/S65camera-hw restart"]) is False
