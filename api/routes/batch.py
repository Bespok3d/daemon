"""The multipart batch-apply routes: update-batch and install-batch. Both stream N .b3 uploads to
the daemon, which applies them all and restarts affected services once, publishing live progress on
the install-progress hub. Split from `packages.py` (recover + uninstall-batch) so each route file
stays within the size ceiling. Blocking work runs off the event loop so the live /ws feeds flow.
"""
import asyncio
import json
import tempfile
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, UploadFile

from core import jinni_client, packages

from ..schemas import PackResultsResponse, PluginRecoveryResult
from .feeds import install_hub

router = APIRouter()

# A batch-apply worker: validate the vars, apply every package deferring restarts, return per-plugin
# results. Both routes pass one of the two below into the shared serve flow.
BatchRunner = Callable[
    [dict[str, str], list[Path], dict[str, dict[str, str]], packages.ProgressSink], list[dict]
]


async def _write_temp_packages(files: list[UploadFile]) -> list[Path]:
    paths: list[Path] = []
    for upload in files:
        tmp = tempfile.NamedTemporaryFile(suffix=".b3", delete=False)
        tmp.write(await upload.read())
        tmp.close()
        paths.append(Path(tmp.name))
    return paths


async def _serve_batch(files: list[UploadFile], vars_json: str, runner: BatchRunner) -> PackResultsResponse:  # noqa: E501
    """Common flow for both batch routes: stage the uploads, open the live progress hub, run the
    blocking apply off the loop, then always close the hub and clean the temp files. A blocked-op
    or conflict from the runner propagates for the route to map; anything else is the runner's own
    HTTPException."""
    vars_by_id: dict[str, dict[str, str]] = json.loads(vars_json) if vars_json else {}
    tmp_paths = await _write_temp_packages(files)
    install_hub.bind_loop(asyncio.get_running_loop())
    install_hub.begin()
    try:
        results = await asyncio.to_thread(
            runner, jinni_client.paths(), tmp_paths, vars_by_id, install_hub.publish,
        )
    except (packages.BlockedActionError, packages.ConflictError, packages.RequirementError, HTTPException):  # noqa: E501
        install_hub.publish({"type": "done", "ok": False})
        raise
    finally:
        for tmp_path in tmp_paths:
            tmp_path.unlink(missing_ok=True)
    ok = all(entry["ok"] for entry in results)
    install_hub.publish({"type": "done", "ok": ok})
    return PackResultsResponse(ok=ok, results=[PluginRecoveryResult(**entry) for entry in results])


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
async def update_batch_packages(files: list[UploadFile], vars_json: str = Form("")) -> PackResultsResponse:  # noqa: E501
    return await _serve_batch(files, vars_json, _update_batch_or_raise)


def _install_batch_or_raise(
    base_vars: dict[str, str],
    tmp_paths: list[Path],
    vars_by_id: dict[str, dict[str, str]],
    publish: packages.ProgressSink,
) -> list[dict]:
    try:
        for user_vars in vars_by_id.values():
            packages.validate_user_vars(user_vars)
        return packages.install_batch(base_vars, tmp_paths, vars_by_id, publish)
    except (packages.BlockedActionError, packages.ConflictError, packages.RequirementError):
        raise
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"{type(exc).__name__}: {exc}") from exc


@router.post(
    "/packages/install-batch",
    response_model=PackResultsResponse,
    summary="Install several plugins at once, restarting affected services only once",
)
async def install_batch_packages(files: list[UploadFile], vars_json: str = Form("")) -> PackResultsResponse:  # noqa: E501
    try:
        return await _serve_batch(files, vars_json, _install_batch_or_raise)
    except packages.ConflictError as exc:
        detail = {"error": "conflict", "plugin_id": exc.plugin_id, "conflicts": exc.conflicts}
        raise HTTPException(status_code=409, detail=detail) from exc
    except packages.RequirementError as exc:
        detail = {"error": "requirement", "plugin_id": exc.plugin_id, "missing": exc.missing}
        raise HTTPException(status_code=409, detail=detail) from exc
