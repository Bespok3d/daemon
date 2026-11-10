# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""An installed plugin's own files: their hashes on the printer, and putting back the ones that
changed.

The app compares the hashes with the signed manifest it holds, and the changed files are then
sent back in a zip of just those files. Both read the manifest the plugin was installed with, so
each answers 404 for a plugin that is not installed, and 422 on a fault of the printer's own, which
the app did not cause.
"""
import asyncio
from pathlib import Path
from typing import BinaryIO

from fastapi import APIRouter, HTTPException, UploadFile

from core import jinni_client, packages

from ..schemas import FileHashesResponse, RestoreFilesResponse
from .refusals import refusal_detail

router = APIRouter()


def _installed_or_raise(plugin_id: str) -> tuple[Path, dict]:
    try:
        plugin_dir = packages.contained_plugin_dir(packages.PLUGIN_ROOT, plugin_id)
    except packages.IntegrityError as refusal:
        raise HTTPException(status_code=409, detail=refusal_detail(refusal)) from refusal
    installed_manifest = packages.readable_manifest(plugin_dir)
    if installed_manifest is None:
        raise HTTPException(status_code=404, detail=plugin_id)
    return plugin_dir, installed_manifest


def _unprocessable(fault: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail=f"{type(fault).__name__}: {fault}")


@router.get(
    "/plugins/{plugin_id}/file-hashes",
    response_model=FileHashesResponse,
    summary="Hash the files an installed plugin keeps on the printer",
    description=(
        "404 when the plugin is not installed or its manifest cannot be read, 409 with the "
        "integrity refusal for an id that leaves the plugin root, 422 on a printer fault."
    ),
)
async def plugin_file_hashes(plugin_id: str) -> FileHashesResponse:
    plugin_dir, installed_manifest = _installed_or_raise(plugin_id)
    try:
        hashes = await asyncio.to_thread(packages.file_hashes, plugin_dir, installed_manifest)
    except Exception as fault:
        raise _unprocessable(fault) from fault
    return FileHashesResponse(files=hashes)


@router.post(
    "/plugins/{plugin_id}/restore-files",
    response_model=RestoreFilesResponse,
    summary="Write back an installed plugin's files from a zip of just those files",
    description=(
        "Every file in the zip must be one the installed manifest lists as kept on disk exactly "
        "as packed, in a folder inside the plugin dir, with the sha256 the manifest lists; "
        "nothing is written until all of them pass. In order: FastAPI's own 400 \"There was an "
        "error parsing the body\" for a multipart body it cannot read, and its own 422, whose "
        "detail is a list, for a request without the multipart `file` part; 409 with the "
        "integrity refusal for an id that leaves the plugin root; 404 when the plugin is not "
        "installed or its manifest cannot be read; 422 when the printer's paths cannot be asked "
        "of the jinni; 409 with the shared blocked answer while the printer blocks any action, as "
        "during a print; 400 when the zip's own directory does not read, or lists a file that is "
        "not stored or deflated, is encrypted, or whose header lies outside the zip; "
        "422 when the unpacked size the zip declares plus the space the daemon keeps in reserve "
        "is more than the printer has free; 409 with the integrity refusal for a file name or "
        "folder; 400 when a file does not unpack; 409 with the integrity refusal for the files "
        "whose bytes differ from the manifest. 422 on any other printer fault, which may come "
        "after some or all of the files were written."
    ),
)
async def restore_plugin_files(plugin_id: str, file: UploadFile) -> RestoreFilesResponse:
    plugin_dir, installed_manifest = _installed_or_raise(plugin_id)
    restored = await asyncio.to_thread(_restore_or_raise, plugin_dir, installed_manifest, file.file)
    return RestoreFilesResponse(restored=restored)


def _restore_or_raise(
    plugin_dir: Path, installed_manifest: dict, upload_stream: BinaryIO,
) -> list[str]:
    try:
        return _restore_upload(plugin_dir, installed_manifest, upload_stream)
    except packages.BlockedActionError:
        raise
    except packages.IntegrityError as refusal:
        raise HTTPException(status_code=409, detail=refusal_detail(refusal)) from refusal
    except packages.DamagedRestoreArchiveError as damage:
        raise HTTPException(status_code=400, detail=str(damage)) from damage
    except Exception as fault:
        raise _unprocessable(fault) from fault


def _restore_upload(
    plugin_dir: Path, installed_manifest: dict, upload_stream: BinaryIO,
) -> list[str]:
    runtime_user = jinni_client.paths().get("RUNTIME_USER", "")
    return packages.restore_files(plugin_dir, installed_manifest, upload_stream, runtime_user)
