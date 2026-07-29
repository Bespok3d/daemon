# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
import asyncio
import contextlib
import re
from pathlib import Path

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from core import auth, jinni_client, packages
from core.data_root import DATA_ROOT
from core.live import install_progress, log_capture, print_state

router = APIRouter()

install_hub = install_progress.InstallProgressHub()


async def _relay_blocked_actions(websocket: WebSocket) -> None:
    """Forward the jinni's blocked-action set to the app, pushed on change. The daemon is a dumb
    relay (ADR-0037): the jinni subscribes to the device and decides; the daemon never reads it.
    When the ws drops, `print_state_feed` cancels this task and awaits it, so cancellation unwinds
    the subscribe generator through its own `finally` rather than an external aclose racing it."""
    async for blocked in jinni_client.subscribe_blocked_actions():
        await websocket.send_json(print_state.app_frame(blocked))


async def _wait_for_client_close(websocket: WebSocket) -> None:
    """Return when the app closes the socket (it never sends), so we can drop the relay side."""
    with contextlib.suppress(WebSocketDisconnect):
        while True:
            await websocket.receive_text()


@router.websocket("/ws/print-state")
async def print_state_feed(websocket: WebSocket, token: str = Query(default="")) -> None:
    """Live blocked-action feed: token-auth the handshake (the HTTP bearer middleware skips ws),
    then relay the jinni's blocked-action set to the app, pushed on change. No polling, no device
    fact in the daemon. The app maps each token to a localized lock reason."""
    if not auth.is_authorized_token(token):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    relay = asyncio.create_task(_relay_blocked_actions(websocket))
    watch = asyncio.create_task(_wait_for_client_close(websocket))
    try:
        await asyncio.wait({relay, watch}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        relay.cancel()
        watch.cancel()
        # Await the cancelled tasks so the relay's subscribe generator unwinds through its own
        # finally (closing the socket to the jinni) before this handler returns.
        await asyncio.gather(relay, watch, return_exceptions=True)
        with contextlib.suppress(Exception):
            await websocket.close()


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
    queue = install_hub.subscribe()
    relay = asyncio.create_task(_relay_install_progress(websocket, queue))
    watch = asyncio.create_task(_wait_for_client_close(websocket))
    try:
        await asyncio.wait({relay, watch}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        relay.cancel()
        watch.cancel()
        install_hub.unsubscribe(queue)
        with contextlib.suppress(Exception):
            await websocket.close()


def _plugin_log_source(plugin_id: str, pattern: str) -> tuple[Path, re.Pattern[str]] | None:
    """Resolve the installed plugin's log file and the capture pattern, or None if there is nothing
    to tail (plugin not installed, or it declares neither a service nor a log path). Refuses an id
    that names anything but its own directory before reading anything under the plugin root."""
    plugin_dir = packages.contained_plugin_dir(packages.PLUGIN_ROOT, plugin_id)
    if not (plugin_dir / "manifest.json").exists():
        return None
    manifest = packages.manifest_at(plugin_dir)
    log_path = log_capture.service_log_path(DATA_ROOT, plugin_dir, manifest)
    if log_path is None:
        return None
    return log_path, log_capture.resolve_pattern(manifest, pattern or None)


def _tailable_log_source(plugin_id: str, pattern: str) -> tuple[Path, re.Pattern[str]] | None:
    """A websocket has one refusal channel, so a refused id yields the same None as an id with
    nothing to tail: the client gets no feed either way."""
    try:
        return _plugin_log_source(plugin_id, pattern)
    except packages.IntegrityError:
        return None


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
    source = _tailable_log_source(plugin_id, pattern)
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
