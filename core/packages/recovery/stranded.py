# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Plugins left switched on while a plugin they need is switched off.

Such a plugin cannot work, yet its config is still wired in, so the printer fails on it at every
start. Its failure is known from the dependency graph alone, before any restart: the safety net
takes all of them off in one round instead of waiting for the printer to fail on each one in turn.
A plugin stranded only by switching another stranded plugin off is found in the same pass.
"""

from pathlib import Path

from ...safety import Decision
from ..daemon_services import DAEMON_SERVICES
from ..deactivation import DEACTIVATED_MARKER, deactivate_plugin
from ..dependencies import order_by_dependency, provided_services, required_services
from ..machinery import is_machinery
from ..manifest import installed_manifests

STRANDED_FIXER = "stranded-plugin"


def unsatisfied_reason(missing_services: list[str]) -> str:
    return f"dependency not satisfied: {', '.join(missing_services)}"


def _stranded_once(manifests: dict[str, dict], switched_off: frozenset[str]) -> dict[str, list[str]]:  # noqa: E501
    """Each switched-on plugin that requires a service which only switched-off plugins provide. A
    service no installed plugin provides at all is not one a switch-off took away, so it is left
    alone here, as recover leaves it."""
    switched_on = {plugin_id: manifest for plugin_id, manifest in manifests.items()
                   if plugin_id not in switched_off}
    served_on = {service for manifest in switched_on.values()
                 for service in provided_services(manifest)} | DAEMON_SERVICES
    served_off = {service for plugin_id in switched_off
                  for service in provided_services(manifests.get(plugin_id, {}))}
    lost = served_off - served_on
    missing = {plugin_id: [service for service in required_services(manifest) if service in lost]
               for plugin_id, manifest in switched_on.items()}
    return {plugin_id: services for plugin_id, services in missing.items() if services}


def stranded_plugins(manifests: dict[str, dict], switched_off: frozenset[str]) -> dict[str, list[str]]:  # noqa: E501
    """Every stranded plugin with the services it lost, providers before the plugins they strand in
    turn. The printer's own machinery is never switched off, so what it provides is never lost. The
    recursion switches at least one more plugin off per call, so it ends within the plugin count."""
    stranded = _stranded_once(manifests, switched_off)
    goes_off = frozenset(plugin_id for plugin_id in stranded if not is_machinery(plugin_id))
    if not goes_off:
        return stranded
    return {**stranded, **stranded_plugins(manifests, switched_off | goes_off)}


def _stranded_among(plugin_root: Path, manifests: dict[str, dict]) -> dict[str, list[str]]:
    switched_off = frozenset(plugin_id for plugin_id in manifests
                             if (plugin_root / plugin_id / DEACTIVATED_MARKER).exists())
    return stranded_plugins(manifests, switched_off)


def installed_stranded(plugin_root: Path) -> dict[str, list[str]]:
    return _stranded_among(plugin_root, installed_manifests(plugin_root))


def _dependents_first(manifests: dict[str, dict], plugin_ids: list[str]) -> list[str]:
    """The plugins ordered so each comes before every plugin it needs, as `deactivator` does."""
    by_node = {Path(plugin_id): manifests[plugin_id] for plugin_id in plugin_ids}
    return [node.name for node in reversed(order_by_dependency(list(by_node), by_node))]


def stranded_decision(plugin_root: Path, handled: list[str]) -> Decision | None:
    """The first stranded plugin not handled yet, as the culprit to take off; None when there is
    none. Picking it needs no evidence: the plugin cannot run without what it needs."""
    stranded = installed_stranded(plugin_root)
    candidates = [plugin_id for plugin_id in stranded if plugin_id not in handled]
    if not candidates:
        return None
    culprit = candidates[0]
    return Decision(culprit, unsatisfied_reason(stranded[culprit]), STRANDED_FIXER)


def switch_off_stranded(plugin_root: Path, vars: dict[str, str]) -> dict[str, list[str]]:
    """Switch every stranded plugin off, the deepest dependents first, each marker naming what it
    lost. Returns each plugin switched off with the services it lost, in that order. The printer's
    own machinery is never taken off, as the net spares it from blame."""
    manifests = installed_manifests(plugin_root)
    stranded = _stranded_among(plugin_root, manifests)
    goes_off = [plugin_id for plugin_id in stranded if not is_machinery(plugin_id)]
    dependents_first = _dependents_first(manifests, goes_off)
    for plugin_id in dependents_first:
        reason = f"auto-deactivated: {unsatisfied_reason(stranded[plugin_id])}"
        deactivate_plugin(plugin_root / plugin_id, vars, reason)
    return {plugin_id: stranded[plugin_id] for plugin_id in dependents_first}
