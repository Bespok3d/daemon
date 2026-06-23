"""Single-plugin command routes: install (streaming), reconfigure, and uninstall.

These act on ONE plugin and live under `/plugins/`; the pack/multi commands (recover, update-batch)
live under `/packages/` in `packages.py`. Install is the one command route with a live side channel:
each phase is published to the install-progress hub as it finishes (so the app's
/ws/install-progress feed shows it live), and the work runs off the event loop.
"""
import asyncio
import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, UploadFile

from core import jinni_client, packages

from ..schemas import InstallResponse, ReconfigureResponse, UninstallResponse
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
    except packages.BlockedActionError as exc:
        detail = {"error": "blocked", "blocked_actions": exc.blocked}
        raise HTTPException(status_code=409, detail=detail) from exc
    except packages.ConflictError as exc:
        detail = {"error": "conflict", "plugin_id": exc.plugin_id, "conflicts": exc.conflicts}
        raise HTTPException(status_code=409, detail=detail) from exc
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
    user_vars: dict[str, str] = json.loads(vars_json) if vars_json else {}
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
        install_hub.publish({"type": "done", "ok": False, "error": _detail_text(exc.detail)})
        raise
    finally:
        tmp_path.unlink(missing_ok=True)


@router.post(
    "/plugins/{plugin_id}/reconfigure",
    response_model=ReconfigureResponse,
    summary="Re-render one plugin's config from new values and restart it",
)
async def reconfigure_plugin(plugin_id: str, user_vars: dict[str, str]) -> ReconfigureResponse:
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
    return ReconfigureResponse.model_validate({"plugin_id": result_id, "ok": True, "log": log})


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
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return UninstallResponse(ok=True, removed=removed)
