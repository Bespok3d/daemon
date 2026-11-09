# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which plugin recovery puts back next, as the plugins before it come back or fail.

Recovery follows the dependency order, but no order fixed beforehand is right for every failure:
when plugins need each other's services, which one can come back first depends on which provider
failed. So before each plugin, recovery checks whether a service it still lacks can come from a
plugin still waiting, and lets that plugin go first.
"""

from pathlib import Path

from ..dependencies import provided_services
from .reapply import ServiceLedger


def next_to_recover(waiting: list[Path], manifests: dict[Path, dict],
                    services: ServiceLedger) -> Path:
    """The first waiting plugin in dependency order that does not wait for a service a plugin still
    waiting can bring back. One always exists: the first plugin that can come back needs nothing
    that is not back."""
    still_coming = _services_still_coming(waiting, manifests, services)
    return next(plugin_dir for plugin_dir in waiting
                if not _waits_for(manifests[plugin_dir], services, still_coming))


def _waits_for(manifest: dict, services: ServiceLedger, still_coming: set[str]) -> bool:
    """A plugin lacking a service nothing waiting can bring back goes now: it is switched off
    either way, so holding it back would only move it out of order."""
    missing = set(services.missing_for(manifest))
    return bool(missing) and missing <= still_coming


def _services_still_coming(waiting: list[Path], manifests: dict[Path, dict],
                           services: ServiceLedger) -> set[str]:
    """The services not back yet that the waiting plugins can still bring back, each plugin once
    the services it needs are."""
    back = services.satisfied
    while True:
        assumed = ServiceLedger(back, services.provided_by_installed)
        brought = _brought_back_by_the_ready(waiting, manifests, assumed)
        if brought <= back:
            return back - services.satisfied
        back = back | brought


def _brought_back_by_the_ready(waiting: list[Path], manifests: dict[Path, dict],
                               assumed: ServiceLedger) -> set[str]:
    """The services the waiting plugins that lack nothing under `assumed` would bring back."""
    ready = [manifests[plugin_dir] for plugin_dir in waiting
             if not assumed.missing_for(manifests[plugin_dir])]
    return {service for manifest in ready for service in provided_services(manifest)}
