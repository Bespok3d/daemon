# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio

from fastapi import APIRouter, HTTPException

from core import jinni_client, packages

from ..schemas import DeactivateResponse, TeardownResponse

router = APIRouter()


# These run off the event loop (asyncio.to_thread): each makes many blocking jinni socket calls and
# restarts services, which on the loop would starve the live feeds and wedge the jinni (ADR-0037).
@router.post(
    "/deactivate",
    response_model=DeactivateResponse,
    summary="Deactivate all plugins without removing files",
)
async def deactivate() -> DeactivateResponse:
    try:
        await asyncio.to_thread(packages.deactivate_all, jinni_client.paths())
    except packages.BlockedActionError as exc:
        raise HTTPException(status_code=409, detail={"error": "blocked", "blocked_actions": exc.blocked}) from exc  # noqa: E501
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DeactivateResponse(ok=True)


@router.post(
    "/teardown",
    response_model=TeardownResponse,
    summary="Uninstall all plugins and remove config hooks; SSH caller removes the workspace",
)
async def teardown() -> TeardownResponse:
    try:
        await asyncio.to_thread(packages.teardown, jinni_client.paths())
    except packages.BlockedActionError as exc:
        raise HTTPException(status_code=409, detail={"error": "blocked", "blocked_actions": exc.blocked}) from exc  # noqa: E501
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TeardownResponse(ok=True)
