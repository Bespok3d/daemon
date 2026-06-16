"""The plain request/response package command routes: reconfigure, recover, update-batch, uninstall.

Each runs its blocking work off the event loop (asyncio.to_thread): the handler stays responsive so
the live feeds (the /ws/print-state relay) are never starved, which would tear their async
generators down mid-await and wedge the jinni. The streaming install route lives in `install.py`.
"""
import asyncio
import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, UploadFile

from core import jinni_client, packages

from ..schemas import (
    PluginRecoveryResult,
    ReconfigureResponse,
    RecoverResponse,
    UninstallResponse,
    UpdateBatchResponse,
)

router = APIRouter()


@router.post(
    "/packages/{plugin_id}/reconfigure",
    response_model=ReconfigureResponse,
    summary="Re-render a plugin's config from new values and restart it",
)
async def reconfigure_package(plugin_id: str, user_vars: dict[str, str]) -> ReconfigureResponse:
    all_vars = {**jinni_client.paths(), **user_vars}
    try:
        packages.validate_user_vars(user_vars)
        result_id, log = await asyncio.to_thread(packages.reconfigure, plugin_id, all_vars, user_vars)  # noqa: E501
    except packages.BlockedActionError:
        raise
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"{type(exc).__name__}: {exc}") from exc
    return ReconfigureResponse(plugin_id=result_id, ok=True, log=log)


@router.post(
    "/packages/recover",
    response_model=RecoverResponse,
    summary="Re-apply all installed plugins after OTA firmware update",
)
async def recover_packages() -> RecoverResponse:
    try:
        # Off the event loop: recover re-applies every plugin over many blocking socket calls and
        # can run for tens of seconds; on the loop it would starve the live feeds (the
        # /ws/print-state relay), tear their async generators down mid-await, and wedge the jinni.
        results = await asyncio.to_thread(packages.recover, jinni_client.paths())
    except packages.BlockedActionError as exc:
        raise HTTPException(status_code=409, detail={"error": "blocked", "blocked_actions": exc.blocked}) from exc  # noqa: E501
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        # Defense in depth: recover_one already isolates per-plugin failures, so reaching here is a
        # top-level fault (the closing restart could not reach the jinni). Report, never a 500.
        raise HTTPException(status_code=422, detail=f"{type(exc).__name__}: {exc}") from exc
    return RecoverResponse(
        ok=all(item["ok"] or item.get("skipped", False) for item in results),
        results=[PluginRecoveryResult(**item) for item in results],
    )


async def _write_temp_packages(files: list[UploadFile]) -> list[Path]:
    paths: list[Path] = []
    for upload in files:
        tmp = tempfile.NamedTemporaryFile(suffix=".b3", delete=False)
        tmp.write(await upload.read())
        tmp.close()
        paths.append(Path(tmp.name))
    return paths


@router.post(
    "/packages/update-batch",
    response_model=UpdateBatchResponse,
    summary="Update several plugins, restarting affected services only once",
)
async def update_batch_packages(
    files: list[UploadFile],
    vars_json: str = Form(""),
) -> UpdateBatchResponse:
    vars_by_id: dict[str, dict[str, str]] = json.loads(vars_json) if vars_json else {}
    tmp_paths = await _write_temp_packages(files)
    try:
        for user_vars in vars_by_id.values():
            packages.validate_user_vars(user_vars)
        results = await asyncio.to_thread(packages.update_batch, jinni_client.paths(), tmp_paths, vars_by_id)  # noqa: E501
    except packages.BlockedActionError:
        raise
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"{type(exc).__name__}: {exc}") from exc
    finally:
        for tmp_path in tmp_paths:
            tmp_path.unlink(missing_ok=True)
    return UpdateBatchResponse(
        ok=all(item["ok"] for item in results),
        results=[PluginRecoveryResult(**item) for item in results],
    )


@router.delete(
    "/packages/{plugin_id}",
    response_model=UninstallResponse,
    summary="Uninstall a plugin",
)
async def uninstall_package(plugin_id: str, cascade: bool = False) -> UninstallResponse:
    try:
        removed = await asyncio.to_thread(packages.uninstall, plugin_id, jinni_client.paths(), cascade)  # noqa: E501
    except packages.DependentsError as exc:
        detail = {"error": "dependents", "plugin_id": exc.plugin_id, "dependents": exc.dependents}
        raise HTTPException(status_code=409, detail=detail) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return UninstallResponse(ok=True, removed=removed)
