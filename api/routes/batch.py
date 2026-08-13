# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The multipart batch-apply routes: update-batch and install-batch. Both stream N .b3 uploads to
the daemon, which applies them all and restarts affected services once, publishing live progress on
the install-progress hub. Split from `packages.py` (recover + uninstall-batch) so each route file
stays within the size ceiling. Blocking work runs off the event loop so the live /ws feeds flow.
"""
import asyncio
import json
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, UploadFile

from core import jinni_client, packages

from ..schemas import PackResultsResponse, PluginRecoveryResult
from .feeds import install_hub

router = APIRouter()

# A batch-apply worker: apply every package deferring restarts, return one result per plugin. Both
# routes pass one of the two below into the shared serve flow.
BatchRunner = Callable[
    [dict[str, str], list[Path], dict[str, dict[str, str]], packages.ProgressSink], list[dict]
]


async def _write_temp_packages(files: list[UploadFile], staging: Path) -> list[Path]:
    """Stage each upload under the name the app gave it, in a slot of its own so two uploads with
    the same name cannot overwrite each other. The name is how a package the daemon cannot even
    open is still reported under the plugin the user picked instead of a random temp name; it comes
    from outside, so only its last component is ever used."""
    paths: list[Path] = []
    for position, upload in enumerate(files):
        slot = staging / str(position)
        slot.mkdir()
        package_path = slot / (Path(upload.filename or "").name or "package.b3")
        package_path.write_bytes(await upload.read())
        paths.append(package_path)
    return paths


async def _serve_batch(files: list[UploadFile], vars_json: str, runner: BatchRunner) -> PackResultsResponse:  # noqa: E501
    """Common flow for both batch routes: stage the uploads, open the live progress hub, run the
    blocking apply off the loop, then always close the hub and clean the temp files. A batch is only
    refused as a whole when it must not run at all, which is a print in progress; anything else is
    the runner's own HTTPException."""
    supplied_by_id: dict[str, dict[str, object]] = json.loads(vars_json) if vars_json else {}
    vars_by_id = {
        plugin_id: packages.user_vars_as_text(supplied)
        for plugin_id, supplied in supplied_by_id.items()
    }
    staging = Path(tempfile.mkdtemp(prefix="b3-batch-"))
    install_hub.bind_loop(asyncio.get_running_loop())
    install_hub.begin()
    try:
        tmp_paths = await _write_temp_packages(files, staging)
        results = await asyncio.to_thread(
            runner, jinni_client.paths(), tmp_paths, vars_by_id, install_hub.publish,
        )
    except (packages.BlockedActionError, HTTPException):
        install_hub.publish({"type": "done", "ok": False})
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
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
        return packages.install_batch(base_vars, tmp_paths, vars_by_id, publish)
    except packages.BlockedActionError:
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
    """A plugin the printer will not accept comes back as its own row saying why, alongside the
    plugins that did install, so one bad pick never costs the user the rest of the call."""
    return await _serve_batch(files, vars_json, _install_batch_or_raise)
