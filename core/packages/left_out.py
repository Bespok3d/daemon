# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which plugins a batch leaves out, and the sentence the user reads for each one. A plugin is left
out either because the printer settled it will not accept it, or because a plugin it needs is not on
the printer at the moment its turn comes.
"""

from pathlib import Path

from ..safety import OperationKind
from .dependencies import required_services, services_the_printer_can_serve


def skipped_result(plugin_id: str, reason: str) -> dict:
    return {"plugin_id": plugin_id, "ok": False, "skipped": True, "reason": reason, "log": []}


def services_already_on_the_printer(plugin_root: Path, batch_ids: frozenset[str]) -> set[str]:
    """The services this printer can already serve (an active plugin outside this batch, or the
    daemon itself), so a plugin is never left out over a service the printer can already serve.
    What a plugin IN the batch owes is decided by the batch itself and never by what is on disk,
    since one of those plugins may still fail and be deactivated while the batch runs."""
    return services_the_printer_can_serve(plugin_root, batch_ids)


def _waiting_on(provider_id: str, kind: OperationKind) -> str:
    """The words the app already shows for a plugin left out because the plugin it needs was left
    out, kept identical here so one user never reads two dialects of the same sentence. An update
    says it plainly instead: the plugin is on the printer, it just did not get the new version."""
    if kind == OperationKind.UPDATE:
        return f'not updated because "{provider_id}", which it needs, is not on the printer'
    return f'not installed because "{provider_id}", which it needs, was not installed either'


def why_not_applied(
    manifest: dict,
    refused: dict[str, str],
    providers: dict[str, tuple[str, ...]],
    satisfied: set[str],
    kind: OperationKind,
) -> str | None:
    """Why this package must not be applied right now, or None to apply it. Either the printer
    already settled it will not accept the package, or a plugin it needs was in this same batch and
    is not on the printer as of this moment (it failed, was rolled back, or was left out itself).
    A package never counts as its own provider, so declaring the service it requires cannot buy it a
    pass out of waiting for the plugin that really supplies it."""
    plugin_id = manifest["name"]
    if plugin_id in refused:
        return refused[plugin_id]
    waited_on = [
        provider
        for service in required_services(manifest) if service not in satisfied
        for provider in providers.get(service, ()) if provider != plugin_id
    ]

    return _waiting_on(waited_on[0], kind) if waited_on else None
