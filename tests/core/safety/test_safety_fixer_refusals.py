# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the fixer chain must REFUSE to do: blame a plugin the evidence does not name, and blame one
it has already switched off. Every wrong blame here costs a user a working plugin, switched off for
a fault that was never its own, so the refusals are tested as hard as the attributions.
"""

from core.safety import AttributionIndex
from core.safety.context import OperationContext, OperationKind
from core.safety.decision import FailureEvidence
from core.safety.fixers import (
    component_failure,
    device_infrastructure,
    last_resort_target,
)
from core.safety.kernel_fixer import kernel_module_failure
from protocol import DeviceHealth, ServiceHealth

CAMERA_PLUGIN = "fake-camera"
BROKER_TOKEN = "stock-broker-down"
STALE_MODULE_TOKEN = "kernel-module:version-magic-mismatch"
NOTIFIER_SERVICE = "fake-notifier-service"


def _no_placements() -> AttributionIndex:
    return AttributionIndex(by_path={}, by_module={}, by_section={})


def _evidence(diagnosis: str = "", module_diagnosis: str = "",
              services: dict[str, ServiceHealth] | None = None) -> FailureEvidence:
    return FailureEvidence(
        health=DeviceHealth(services=services or {}, diagnosis=diagnosis),
        index=_no_placements(),
        module_diagnosis=module_diagnosis,
    )


def _installing(plugin_id: str | None = CAMERA_PLUGIN) -> OperationContext:
    return OperationContext(kind=OperationKind.INSTALL, plugin_id=plugin_id)


def test_a_token_that_is_not_about_a_kernel_module_blames_nobody() -> None:
    """The printer's own broker being down is not the installed plugin's stale module, so the
    kernel fixer must pass and let the device-infrastructure relay answer instead."""
    evidence = _evidence(module_diagnosis=BROKER_TOKEN)

    assert kernel_module_failure(evidence, _installing(), []) is None


def test_a_plugin_already_switched_off_is_not_blamed_a_second_time() -> None:
    evidence = _evidence(module_diagnosis=STALE_MODULE_TOKEN)

    assert kernel_module_failure(evidence, _installing(), [CAMERA_PLUGIN]) is None


def test_the_kernel_fixer_stays_out_of_a_plain_service_restart() -> None:
    """No module was loaded, so there is no module verdict to read: the fixer must stay inert
    rather than blame whichever plugin the operation happened to touch."""
    evidence = _evidence(module_diagnosis="")

    assert kernel_module_failure(evidence, _installing(), []) is None


def test_a_fault_the_printer_owns_switches_no_plugin_off() -> None:
    """The jinni named a cause that is not a plugin. The user is told the token and every plugin
    keeps running."""
    decision = device_infrastructure(_evidence(diagnosis=BROKER_TOKEN), _installing(), [])

    assert decision is not None
    assert decision.culprit is None
    assert decision.signal == BROKER_TOKEN


def test_a_failed_part_that_no_installed_plugin_switched_on_blames_nobody() -> None:
    """The failed component matches no config section any plugin placed, so it is the printer's
    own, and no plugin is switched off for it."""
    sick_service = ServiceHealth(ready=True, detail="", failed_components=("notifier",))
    evidence = _evidence(services={NOTIFIER_SERVICE: sick_service})

    assert component_failure(evidence, _installing(), []) is None


def test_nothing_is_blamed_when_no_plugin_was_being_worked_on() -> None:
    """A restart with no plugin under the daemon's hands (a recover sweep) has no last resort to
    fall back on: it must reach the catch-all instead of inventing a culprit."""
    assert last_resort_target(_evidence(), _installing(plugin_id=None), []) is None
