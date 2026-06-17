"""The pack/multi-plugin command routes: recover (all installed plugins) and update-batch (a set).

Both act on more than one plugin and live under `/packages/`; the single-plugin commands (install,
reconfigure, uninstall) live under `/plugins/` in `plugins.py`. Each runs its blocking work off the
event loop (asyncio.to_thread), keeping the handler responsive so the live /ws feeds keep flowing.
"""
import asyncio
import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, UploadFile
from pydantic import BaseModel

from core import jinni_client, packages

from ..schemas import (
    PackResultsResponse,
    PluginRecoveryResult,
)
from .feeds import install_hub

router = APIRouter()


@router.post(
    "/packages/recover",
    response_model=PackResultsResponse,
    summary="Re-apply all installed plugins after OTA firmware update",
)
async def recover_packages() -> PackResultsResponse:
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
    return PackResultsResponse(
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


def _update_batch_or_raise(
    base_vars: dict[str, str],
    tmp_paths: list[Path],
    vars_by_id: dict[str, dict[str, str]],
    publish: packages.ProgressSink,
) -> list[dict]:
    try:
        for user_vars in vars_by_id.values():
            packages.validate_user_vars(user_vars)
        return packages.update_batch(base_vars, tmp_paths, vars_by_id, publish)
    except packages.BlockedActionError:
        raise
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"{type(exc).__name__}: {exc}") from exc


@router.post(
    "/packages/update-batch",
    response_model=PackResultsResponse,
    summary="Update several plugins, restarting affected services only once",
)
async def update_batch_packages(
    files: list[UploadFile],
    vars_json: str = Form(""),
) -> PackResultsResponse:
    vars_by_id: dict[str, dict[str, str]] = json.loads(vars_json) if vars_json else {}
    tmp_paths = await _write_temp_packages(files)
    install_hub.bind_loop(asyncio.get_running_loop())
    install_hub.begin()
    try:
        results = await asyncio.to_thread(
            _update_batch_or_raise,
            jinni_client.paths(), tmp_paths, vars_by_id, install_hub.publish,
        )
    except (packages.BlockedActionError, HTTPException):
        install_hub.publish({"type": "done", "ok": False})
        raise
    finally:
        for tmp_path in tmp_paths:
            tmp_path.unlink(missing_ok=True)
    ok = all(entry["ok"] for entry in results)
    install_hub.publish({"type": "done", "ok": ok})
    return PackResultsResponse(
        ok=ok,
        results=[PluginRecoveryResult(**entry) for entry in results],
    )


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
    except packages.BlockedActionError:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PackResultsResponse(
        ok=all(entry["ok"] or entry.get("skipped", False) for entry in results),
        results=[PluginRecoveryResult(**entry) for entry in results],
    )
