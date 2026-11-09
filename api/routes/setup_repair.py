# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The narrow repair route: put the printer's own setup right without re-applying any plugin.

A 409 `needs_recover` tells the caller selfcheck found more than a setup fault (or nothing), and the
full POST /packages/recover is the right repair. The caller reboots the printer after a success.
"""
import asyncio

from fastapi import APIRouter, HTTPException

from core import jinni_client, packages
from core.selfcheck import run_selfcheck

from ..schemas import PackResultsResponse, PluginRecoveryResult

router = APIRouter()


@router.post(
    "/packages/repair-setup",
    response_model=PackResultsResponse,
    summary="Repair a setup-only fault (include lines, directories, leftovers) without re-applying plugins",  # noqa: E501
)
async def repair_setup() -> PackResultsResponse:
    try:
        results = await asyncio.to_thread(
            packages.repair_setup, jinni_client.paths(), run_selfcheck,
        )
    except packages.NeedsFullRecoverError as exc:
        raise HTTPException(status_code=409, detail={"error": "needs_recover"}) from exc
    except packages.BlockedActionError as exc:
        raise HTTPException(status_code=409, detail={"error": "blocked", "blocked_actions": exc.blocked}) from exc  # noqa: E501
    return PackResultsResponse(
        ok=all(entry["ok"] for entry in results),
        results=[PluginRecoveryResult(**entry) for entry in results],
    )
