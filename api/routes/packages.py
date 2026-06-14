import asyncio
import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, UploadFile

from core import packages
from jinni.loader import get_jinni

from ..schemas import (
    InstallResponse,
    PluginRecoveryResult,
    ReconfigureResponse,
    RecoverResponse,
    UninstallResponse,
    UpdateBatchResponse,
)
from .feeds import install_hub

router = APIRouter()


def _detail_text(detail: object) -> str:
    """A failed install's HTTPException detail is a plain string for most errors and a dict for a
    conflict; flatten either into a single line for the progress feed's terminal event."""
    if isinstance(detail, dict):
        return str(detail.get("error", detail))
    return str(detail)


def _install_or_raise(
    tmp_path: Path, all_vars: dict[str, str], user_vars: dict[str, str],
    on_phase: packages.PhaseListener | None = None,
) -> InstallResponse:
    try:
        packages.validate_user_vars(user_vars)
        plugin_id, install_log = packages.install(
            tmp_path, all_vars, user_vars=user_vars, on_phase=on_phase,
        )
    except packages.ConflictError as exc:
        detail = {"error": "conflict", "plugin_id": exc.plugin_id, "conflicts": exc.conflicts}
        raise HTTPException(status_code=409, detail=detail) from exc
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"{type(exc).__name__}: {exc}") from exc
    return InstallResponse(plugin_id=plugin_id, ok=True, log=install_log)


@router.post(
    "/packages/install",
    response_model=InstallResponse,
    summary="Install a plugin package",
)
async def install_package(
    file: UploadFile,
    vars_json: str = Form(""),
) -> InstallResponse:
    user_vars: dict[str, str] = json.loads(vars_json) if vars_json else {}
    jinni = get_jinni()
    all_vars = {**jinni.paths(), **user_vars}
    tmp = tempfile.NamedTemporaryFile(suffix=".b3", delete=False)
    tmp_path = Path(tmp.name)
    tmp.write(await file.read())
    tmp.close()
    install_hub.bind_loop(asyncio.get_running_loop())
    install_hub.begin()

    def on_phase(phase: dict) -> None:
        install_hub.publish({"type": "phase", "phase": phase})

    try:
        response = await asyncio.to_thread(
            _install_or_raise, tmp_path, all_vars, user_vars, on_phase,
        )
        install_hub.publish({"type": "done", "ok": response.ok})
        return response
    except HTTPException as exc:
        install_hub.publish({"type": "done", "ok": False, "error": _detail_text(exc.detail)})
        raise
    finally:
        tmp_path.unlink(missing_ok=True)


@router.post(
    "/packages/{plugin_id}/reconfigure",
    response_model=ReconfigureResponse,
    summary="Re-render a plugin's config from new values and restart it",
)
async def reconfigure_package(plugin_id: str, user_vars: dict[str, str]) -> ReconfigureResponse:
    jinni = get_jinni()
    all_vars = {**jinni.paths(), **user_vars}
    try:
        packages.validate_user_vars(user_vars)
        result_id, log = packages.reconfigure(plugin_id, all_vars, user_vars)
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
    jinni = get_jinni()
    try:
        results = packages.recover(jinni.paths())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    jinni = get_jinni()
    vars_by_id: dict[str, dict[str, str]] = json.loads(vars_json) if vars_json else {}
    tmp_paths = await _write_temp_packages(files)
    try:
        for user_vars in vars_by_id.values():
            packages.validate_user_vars(user_vars)
        results = packages.update_batch(jinni.paths(), tmp_paths, vars_by_id)
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
    jinni = get_jinni()
    try:
        removed = packages.uninstall(plugin_id, jinni.paths(), cascade=cascade)
    except packages.DependentsError as exc:
        detail = {"error": "dependents", "plugin_id": exc.plugin_id, "dependents": exc.dependents}
        raise HTTPException(status_code=409, detail=detail) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return UninstallResponse(ok=True, removed=removed)
