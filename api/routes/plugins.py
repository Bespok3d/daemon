# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Single-plugin commands that answer the caller directly: reconfigure, deactivate, uninstall,
and the config read.

These act on ONE plugin and live under `/plugins/`. Install is next door in `plugin_install.py`,
because it streams its progress while it works; the pack commands (recover, update-batch) live
under `/packages/` in `packages.py`.
"""
import asyncio

from fastapi import APIRouter, HTTPException

from core import jinni_client, packages

from ..schemas import (
    PluginConfigResponse,
    PluginDeactivateResponse,
    ReconfigureResponse,
    UninstallResponse,
)
from .refusals import refusal_detail

router = APIRouter()


@router.post(
    "/plugins/{plugin_id}/reconfigure",
    response_model=ReconfigureResponse,
    summary="Re-render one plugin's config from new values and restart it",
)
async def reconfigure_plugin(plugin_id: str, supplied_vars: dict[str, object]) -> ReconfigureResponse:  # noqa: E501
    user_vars = packages.user_vars_as_text(supplied_vars)
    all_vars = {**jinni_client.paths(), **user_vars}
    try:
        packages.validate_user_vars(user_vars)
        result_id, log = await asyncio.to_thread(packages.reconfigure, plugin_id, all_vars, user_vars)  # noqa: E501
    except packages.BlockedActionError:
        raise
    except (packages.IntegrityError, packages.MissingSettingError) as exc:
        raise HTTPException(status_code=409, detail=refusal_detail(exc)) from exc
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"{type(exc).__name__}: {exc}") from exc
    return ReconfigureResponse.model_validate({"plugin_id": result_id, "ok": True, "log": log})


@router.get(
    "/plugins/{plugin_id}/config",
    response_model=PluginConfigResponse,
    summary="Read one plugin's persisted install-time user variables",
    description=(
        "Returns the user variables the plugin was installed or last reconfigured with, as "
        "persisted next to the plugin on the printer. Empty for a plugin that took none."
    ),
)
async def plugin_config(plugin_id: str) -> PluginConfigResponse:
    try:
        plugin_dir = packages.contained_plugin_dir(packages.PLUGIN_ROOT, plugin_id)
    except packages.IntegrityError as exc:
        raise HTTPException(status_code=409, detail=refusal_detail(exc)) from exc
    if not plugin_dir.is_dir():
        raise HTTPException(status_code=404, detail=plugin_id)
    return PluginConfigResponse(vars=packages.load_user_vars(plugin_dir))


@router.delete(
    "/plugins/{plugin_id}",
    response_model=UninstallResponse,
    summary="Uninstall one plugin",
)
async def uninstall_plugin(plugin_id: str, cascade: bool = False) -> UninstallResponse:
    try:
        removed = await asyncio.to_thread(packages.uninstall, plugin_id, jinni_client.paths(), cascade)  # noqa: E501
    except packages.DependentsError as exc:
        detail = {"error": "dependents", "plugin_id": exc.plugin_id, "dependents": exc.dependents}
        raise HTTPException(status_code=409, detail=detail) from exc
    except packages.IntegrityError as exc:
        raise HTTPException(status_code=409, detail=refusal_detail(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return UninstallResponse(ok=True, removed=removed)


@router.post(
    "/plugins/{plugin_id}/deactivate",
    response_model=PluginDeactivateResponse,
    summary="Deactivate one plugin, keeping its files",
)
async def deactivate_plugin(plugin_id: str, cascade: bool = False) -> PluginDeactivateResponse:
    try:
        deactivated = await asyncio.to_thread(packages.deactivate, plugin_id, jinni_client.paths(), cascade)  # noqa: E501
    except packages.DependentsError as exc:
        detail = {"error": "dependents", "plugin_id": exc.plugin_id, "dependents": exc.dependents}
        raise HTTPException(status_code=409, detail=detail) from exc
    except packages.BlockedActionError as exc:
        raise HTTPException(status_code=409, detail={"error": "blocked", "blocked_actions": exc.blocked}) from exc  # noqa: E501
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PluginDeactivateResponse(ok=True, deactivated=deactivated)
