# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The active watch: its setting and its live feed to the app.

The setting handlers are plain functions: FastAPI runs them in its thread pool, where a changed
setting may wait for the reader threads to stop without holding up the event loop.
"""
import threading

from fastapi import APIRouter, Query, WebSocket

from core import auth
from core.watch.hub import ActiveWatchHub
from core.watch.runner import WatchRunner
from core.watch.settings import complete_settings, load_settings, save_settings

from ..schemas import ActiveWatchSetting
from .feed_relay import relay_queue, relay_until_client_closes

router = APIRouter()

watch_hub = ActiveWatchHub()
watch_runner = WatchRunner(watch_hub)
setting_change_lock = threading.Lock()
"""Two changes at once must leave the watch running on the setting that was saved last."""


@router.get(
    "/active-watch",
    response_model=ActiveWatchSetting,
    summary="Read the active-watch setting",
)
def active_watch_setting() -> ActiveWatchSetting:
    return ActiveWatchSetting(**load_settings())


@router.put(
    "/active-watch",
    response_model=ActiveWatchSetting,
    summary="Change the active-watch setting; the watch picks it up at once",
)
def change_active_watch_setting(body: ActiveWatchSetting) -> ActiveWatchSetting:
    chosen = complete_settings(body.enabled, body.files, body.remedies)
    with setting_change_lock:
        save_settings(chosen)
        watch_runner.restart(chosen)
    return ActiveWatchSetting(**chosen)


@router.websocket("/ws/active-watch")
async def active_watch_feed(websocket: WebSocket, token: str = Query(default="")) -> None:
    """Live active-watch frames: token-auth the handshake (the HTTP bearer middleware skips ws),
    then send each remedy the watch carries out, as {token, remedy}, plus the reboot id on a reboot
    and on the notify that takes it back. Nothing is replayed. The app is subscribed before the
    handshake completes, so no frame falls between the two."""
    if not auth.is_authorized_token(token):
        await websocket.close(code=1008)
        return
    queue = watch_hub.subscribe()
    try:
        await websocket.accept()
        await relay_until_client_closes(websocket, relay_queue(websocket, queue))
    finally:
        watch_hub.unsubscribe(queue)
