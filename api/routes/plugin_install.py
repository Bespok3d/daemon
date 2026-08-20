# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The install route: take one uploaded package, install it, and report every phase as it
finishes.

Install is the one single-plugin command with a live side channel: each phase is published to
the install-progress hub as it completes (so the app's /ws/install-progress feed shows it live)
and the work itself runs off the event loop. The plain single-plugin commands, which just answer
the caller, are in `plugins.py`.
"""
import asyncio
import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, UploadFile

from core import jinni_client, packages

from ..schemas import InstallResponse
from .feeds import install_hub
from .refusals import REFUSALS, detail_text, refusal_detail

router = APIRouter()


def _install_or_raise(
    tmp_path: Path, all_vars: dict[str, str], user_vars: dict[str, str],
    on_phase: packages.PhaseListener | None = None,
) -> InstallResponse:
    try:
        packages.validate_user_vars(user_vars)
        plugin_id, install_log = packages.install(
            tmp_path, all_vars, user_vars=user_vars, on_phase=on_phase,
        )
    except REFUSALS as exc:
        raise HTTPException(status_code=409, detail=refusal_detail(exc)) from exc
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"{type(exc).__name__}: {exc}") from exc
    install_ok = all(logged_phase["ok"] for logged_phase in install_log)
    # model_validate coerces the executor's phase dicts into InstallLogPhase, keeping the strict
    # typing at the API boundary without retyping core.results (which stays dict-based internally).
    return InstallResponse.model_validate(
        {"plugin_id": plugin_id, "ok": install_ok, "log": install_log}
    )


@router.post(
    "/plugins/install",
    response_model=InstallResponse,
    summary="Install one plugin package",
)
async def install_plugin(
    file: UploadFile,
    vars_json: str = Form(""),
) -> InstallResponse:
    user_vars = packages.user_vars_as_text(json.loads(vars_json) if vars_json else {})
    all_vars = {**jinni_client.paths(), **user_vars}
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
        install_hub.publish({"type": "done", "ok": False, "error": detail_text(exc.detail)})
        raise
    finally:
        tmp_path.unlink(missing_ok=True)
