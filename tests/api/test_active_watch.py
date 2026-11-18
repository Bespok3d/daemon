# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
from collections.abc import AsyncIterator, Generator
from functools import partial
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from api import app
from api.routes import active_watch as routes_active_watch
from core.watch import settings
from core.watch.runner import WatchRunner
from tests.fake_owner import ISSUED_TOKEN

pytestmark = pytest.mark.usefixtures("daemon_acl")

DEFAULT_SETTING = {"enabled": True, "files": ["/dev/kmsg"], "remedies": {"screen-stuck": "notify"}}


@pytest.fixture(autouse=True)
def setting_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "active-watch.json")


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
        headers={"Authorization": f"Bearer {ISSUED_TOKEN}"},
    ) as daemon_client:
        yield daemon_client


async def test_the_setting_reads_the_defaults_when_none_was_saved(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/active-watch")
    assert response.status_code == 200
    assert response.json() == DEFAULT_SETTING


async def test_a_changed_setting_is_saved_and_read_back(client: httpx.AsyncClient) -> None:
    chosen = {**DEFAULT_SETTING, "remedies": {"screen-stuck": "reboot-when-idle"}}
    assert (await client.put("/active-watch", json=chosen)).json() == chosen
    assert (await client.get("/active-watch")).json() == chosen


async def test_a_setting_without_a_detector_still_lists_it(client: httpx.AsyncClient) -> None:
    response = await client.put("/active-watch", json={**DEFAULT_SETTING, "remedies": {}})
    assert response.json() == DEFAULT_SETTING


async def test_an_unknown_remedy_is_refused(client: httpx.AsyncClient) -> None:
    refused = {**DEFAULT_SETTING, "remedies": {"screen-stuck": "explode"}}
    assert (await client.put("/active-watch", json=refused)).status_code == 422
    assert (await client.get("/active-watch")).json() == DEFAULT_SETTING


def recording_reader(
    opened_files: list[str], path: str, wake_read_fd: int,
) -> Generator[str, None, None]:
    opened_files.append(path)
    yield from ()


async def test_a_changed_setting_never_starts_a_watch_the_daemon_did_not(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened_files: list[str] = []
    reader = partial(recording_reader, opened_files)
    runner = WatchRunner(routes_active_watch.watch_hub, readers={"/dev/kmsg": reader})
    monkeypatch.setattr(routes_active_watch, "watch_runner", runner)
    await client.put("/active-watch", json=DEFAULT_SETTING)
    runner.stop()
    assert opened_files == []


def test_the_feed_refuses_a_bad_token() -> None:
    with pytest.raises(WebSocketDisconnect):
        with TestClient(app).websocket_connect("/ws/active-watch?token=wrong") as feed:
            feed.receive_json()


def test_the_feed_sends_each_remedy_to_the_app() -> None:
    url = f"/ws/active-watch?token={ISSUED_TOKEN}"
    with TestClient(app).websocket_connect(url) as feed:
        routes_active_watch.watch_hub.publish({"token": "screen-stuck", "remedy": "notify"})
        assert feed.receive_json() == {"token": "screen-stuck", "remedy": "notify"}
