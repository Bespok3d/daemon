# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The pack/multi-plugin command routes that are NOT multipart uploads: recover (re-apply all
installed plugins) and uninstall-batch (a set). Both act on more than one plugin and live under
`/packages/`; the multipart batch-apply routes (update-batch, install-batch) live in `batch.py`, and
the single-plugin commands (install, reconfigure, uninstall) under `/plugins/` in `plugins.py`. Each
runs its blocking work off the event loop (asyncio.to_thread) so the live /ws feeds keep flowing.
"""
import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core import jinni_client, packages

from ..schemas import (
    PackResultsResponse,
    PluginRecoveryResult,
)
from .feeds import install_hub
from .refusals import refusal_detail

router = APIRouter()


@router.post(
    "/packages/recover",
    response_model=PackResultsResponse,
    summary="Re-apply all installed plugins after OTA firmware update",
)
async def recover_packages() -> PackResultsResponse:
    install_hub.bind_loop(asyncio.get_running_loop())
    install_hub.begin()
    try:
        results = await _recover_or_refuse()
    except HTTPException:
        install_hub.publish({"type": "done", "ok": False})
        raise
    ok = all(item["ok"] or item.get("skipped", False) for item in results)
    install_hub.publish({"type": "done", "ok": ok})

    return PackResultsResponse(
        ok=ok,
        results=[PluginRecoveryResult(**item) for item in results],
    )


async def _recover_or_refuse() -> list[dict]:
    """Re-apply everything installed, reporting a refusal as its own status rather than a 500."""
    try:
        # Off the event loop: recover re-applies every plugin over many blocking socket calls and
        # can run for tens of seconds; on the loop it would starve the live feeds (the
        # /ws/print-state relay), tear their async generators down mid-await, and wedge the jinni.
        return await asyncio.to_thread(packages.recover, jinni_client.paths(), install_hub.publish)
    except packages.BlockedActionError as exc:
        raise HTTPException(status_code=409, detail={"error": "blocked", "blocked_actions": exc.blocked}) from exc  # noqa: E501
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        # Defense in depth: recover_one already isolates per-plugin failures, so reaching here is a
        # top-level fault (the closing restart could not reach the jinni). Report, never a 500.
        raise HTTPException(status_code=422, detail=f"{type(exc).__name__}: {exc}") from exc


class UninstallBatchBody(BaseModel):
    plugin_ids: list[str]
    cascade: bool = False


@router.post(
    "/packages/uninstall-batch",
    response_model=PackResultsResponse,
    summary="Uninstall several plugins, restarting affected services only once",
)
async def uninstall_batch_packages(body: UninstallBatchBody) -> PackResultsResponse:
    try:
        results = await asyncio.to_thread(
            packages.uninstall_batch, body.plugin_ids, jinni_client.paths(), body.cascade,
        )
    except packages.DependentsError as exc:
        detail = {"error": "dependents", "plugin_id": exc.plugin_id, "dependents": exc.dependents}
        raise HTTPException(status_code=409, detail=detail) from exc
    except packages.IntegrityError as exc:
        raise HTTPException(status_code=409, detail=refusal_detail(exc)) from exc
    except packages.BlockedActionError:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PackResultsResponse(
        ok=all(entry["ok"] or entry.get("skipped", False) for entry in results),
        results=[PluginRecoveryResult(**entry) for entry in results],
    )
