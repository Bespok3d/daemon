import asyncio
import contextlib
import json
import os
import re
import tempfile
from pathlib import Path

import websockets
from fastapi import (
    APIRouter,
    Form,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)

from core import auth, log_capture, packages, print_events
from core.capabilities import get_capabilities
from core.install_progress import InstallProgressHub
from core.selfcheck import run_selfcheck
from jinni.loader import get_jinni
from version import DAEMON_VERSION

from .schemas import (
    AccessActionResponse,
    AccessClient,
    AccessClientsResponse,
    AccessIdentityBody,
    AccessRequestBody,
    AccessRequestResponse,
    CapabilitiesResponse,
    DeactivateResponse,
    InstallResponse,
    PendingClient,
    PluginDrift,
    PluginRecoveryResult,
    ReconfigureResponse,
    RecoverResponse,
    SelfCheckResponse,
    StatusResponse,
    TeardownResponse,
    UninstallResponse,
    UpdateBatchResponse,
)

router = APIRouter()

_install_hub = InstallProgressHub()

_DATA_ROOT = Path(os.environ.get("BESPOK3D_DATA_ROOT", "/userdata/bespok3d"))
_CERT_PATH = _DATA_ROOT / "etc/daemon/server.crt"


def _server_cert() -> str:
    return _CERT_PATH.read_text() if _CERT_PATH.exists() else ""


@router.get("/status", response_model=StatusResponse, summary="Daemon health check")
async def status() -> StatusResponse:
    return StatusResponse(ok=True, version=DAEMON_VERSION)


_MOONRAKER_WS = "ws://localhost:7125/websocket"


async def _relay_moonraker_state(websocket: WebSocket) -> None:
    """Subscribe to Moonraker print_stats and forward each {active,state} change to the app."""
    async with websockets.connect(_MOONRAKER_WS) as moonraker:
        await moonraker.send(print_events.subscribe_message())
        async for raw in moonraker:
            event = print_events.print_state_event(json.loads(raw))
            if event is not None:
                await websocket.send_json(event)


async def _wait_for_client_close(websocket: WebSocket) -> None:
    """Return when the app closes the socket (it never sends), so we can drop the Moonraker side."""
    with contextlib.suppress(WebSocketDisconnect):
        while True:
            await websocket.receive_text()


@router.websocket("/ws/print-state")
async def print_state_feed(websocket: WebSocket, token: str = Query(default="")) -> None:
    """Live print-state feed: token-auth the handshake (the HTTP bearer middleware skips ws), then
    bridge Moonraker print_stats to the app, pushing only on change. No polling."""
    if not auth.is_authorized_token(token):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    relay = asyncio.create_task(_relay_moonraker_state(websocket))
    watch = asyncio.create_task(_wait_for_client_close(websocket))
    try:
        await asyncio.wait({relay, watch}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        relay.cancel()
        watch.cancel()
        with contextlib.suppress(Exception):
            await websocket.send_json({"active": False, "state": ""})
        with contextlib.suppress(Exception):
            await websocket.close()


def _detail_text(detail: object) -> str:
    """A failed install's HTTPException detail is a plain string for most errors and a dict for a
    conflict; flatten either into a single line for the progress feed's terminal event."""
    if isinstance(detail, dict):
        return str(detail.get("error", detail))
    return str(detail)


async def _relay_install_progress(websocket: WebSocket, queue: "asyncio.Queue[dict]") -> None:
    while True:
        await websocket.send_json(await queue.get())


@router.websocket("/ws/install-progress")
async def install_progress_feed(websocket: WebSocket, token: str = Query(default="")) -> None:
    """Live install-progress feed: token-auth the handshake (the HTTP bearer middleware skips ws),
    then stream each install phase as it finishes plus a terminal {type:'done', ok}. The current
    run's events are replayed on connect, so opening the socket just before the install POST never
    loses the first phase."""
    if not auth.is_authorized_token(token):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    queue = _install_hub.subscribe()
    relay = asyncio.create_task(_relay_install_progress(websocket, queue))
    watch = asyncio.create_task(_wait_for_client_close(websocket))
    try:
        await asyncio.wait({relay, watch}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        relay.cancel()
        watch.cancel()
        _install_hub.unsubscribe(queue)
        with contextlib.suppress(Exception):
            await websocket.close()


def _plugin_log_source(plugin_id: str, pattern: str) -> tuple[Path, re.Pattern[str]] | None:
    """Resolve the installed plugin's log file and the capture pattern, or None if there is nothing
    to tail (plugin not installed, or it declares neither a service nor a log path)."""
    plugin_dir = packages.PLUGIN_ROOT / plugin_id
    if not (plugin_dir / "manifest.json").exists():
        return None
    manifest = packages._manifest_at(plugin_dir)
    log_path = log_capture.service_log_path(_DATA_ROOT, plugin_dir, manifest)
    if log_path is None:
        return None
    return log_path, log_capture.resolve_pattern(manifest, pattern or None)


async def _relay_plugin_log(
    websocket: WebSocket, log_path: Path, pattern: re.Pattern[str], pattern_name: str,
) -> None:
    async for value in log_capture.tail_and_capture(log_path, pattern):
        await websocket.send_json({"value": value, "pattern": pattern_name})


@router.websocket("/ws/plugin-log/{plugin_id}")
async def plugin_log_feed(
    websocket: WebSocket,
    plugin_id: str,
    token: str = Query(default=""),
    pattern: str = Query(default=""),
) -> None:
    """Tail an installed plugin's service log and stream each new match (URLs by default) to the
    app, so a one-time link the service prints reaches the user without SSH. Token-auths the
    handshake (the HTTP bearer middleware skips ws) and re-emits current matches on connect."""
    if not auth.is_authorized_token(token):
        await websocket.close(code=1008)
        return
    source = _plugin_log_source(plugin_id, pattern)
    if source is None:
        await websocket.close(code=1008)
        return
    log_path, compiled = source
    await websocket.accept()
    relay = asyncio.create_task(_relay_plugin_log(websocket, log_path, compiled, pattern or "url"))
    watch = asyncio.create_task(_wait_for_client_close(websocket))
    try:
        await asyncio.wait({relay, watch}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        relay.cancel()
        watch.cancel()
        with contextlib.suppress(Exception):
            await websocket.close()


@router.get(
    "/capabilities",
    response_model=CapabilitiesResponse,
    summary="Printer capabilities",
    description="Hardware features, installed plugins, and Klipper version.",
)
async def capabilities() -> CapabilitiesResponse:
    return get_capabilities()


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
    _install_hub.bind_loop(asyncio.get_running_loop())
    _install_hub.begin()

    def on_phase(phase: dict) -> None:
        _install_hub.publish({"type": "phase", "phase": phase})

    try:
        response = await asyncio.to_thread(
            _install_or_raise, tmp_path, all_vars, user_vars, on_phase,
        )
        _install_hub.publish({"type": "done", "ok": response.ok})
        return response
    except HTTPException as exc:
        _install_hub.publish({"type": "done", "ok": False, "error": _detail_text(exc.detail)})
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


@router.post(
    "/deactivate",
    response_model=DeactivateResponse,
    summary="Deactivate all plugins without removing files",
)
async def deactivate() -> DeactivateResponse:
    jinni = get_jinni()
    try:
        packages.deactivate_all(jinni.paths())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DeactivateResponse(ok=True)


@router.post(
    "/teardown",
    response_model=TeardownResponse,
    summary="Uninstall all plugins and remove config hooks; SSH caller removes the workspace",
)
async def teardown() -> TeardownResponse:
    jinni = get_jinni()
    try:
        packages.teardown(jinni.paths())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TeardownResponse(ok=True)


@router.post(
    "/access/request",
    response_model=AccessRequestResponse,
    summary="Request access to this printer (unauthenticated; an existing client must approve)",
)
async def access_request(body: AccessRequestBody) -> AccessRequestResponse:
    if not auth.valid_access_request(body.identity, body.token, body.label, body.public_key or ""):
        raise HTTPException(status_code=400, detail="invalid access request")
    entry = {"identity": body.identity, "label": body.label,
             "public_key": body.public_key or "", "token": body.token}
    if not auth.add_pending(entry):
        raise HTTPException(status_code=429, detail="too many pending access requests")
    return AccessRequestResponse(ok=True, cert=_server_cert())


@router.get(
    "/access/clients",
    response_model=AccessClientsResponse,
    summary="List authorized clients and pending access requests",
)
async def access_clients() -> AccessClientsResponse:
    return AccessClientsResponse(
        clients=[AccessClient(**client) for client in auth.list_clients()],
        pending=[PendingClient(**item) for item in auth.list_pending()],
    )


@router.post(
    "/access/grant",
    response_model=AccessActionResponse,
    summary="Approve a pending access request (any authorized client may grant)",
)
async def access_grant(body: AccessIdentityBody) -> AccessActionResponse:
    entry = auth.pop_pending(body.identity)
    if entry is None:
        raise HTTPException(status_code=404, detail="no such pending request")
    auth.grant_key(body.identity, entry["token"], role="user", label=entry.get("label", ""))
    return AccessActionResponse(ok=True)


@router.post(
    "/access/revoke",
    response_model=AccessActionResponse,
    summary="Remove an authorized client (any authorized client may revoke)",
)
async def access_revoke(body: AccessIdentityBody) -> AccessActionResponse:
    auth.revoke_key(body.identity)
    return AccessActionResponse(ok=True)


@router.get(
    "/selfcheck",
    response_model=SelfCheckResponse,
    summary="Compare expected on-printer plugin state to the actual filesystem",
    description=(
        "Read-only drift scan. For every active plugin, verifies that the symlinks declared "
        "in its manifest exist and point at the right source. Returns an empty drift list when "
        "everything is in order."
    ),
)
async def selfcheck() -> SelfCheckResponse:
    jinni = get_jinni()
    drift_raw = run_selfcheck(jinni.paths())
    drift = [PluginDrift(**report) for report in drift_raw]
    return SelfCheckResponse(ok=len(drift) == 0, drift=drift)
