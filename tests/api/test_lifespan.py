# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
import logging

import pytest

import api
from core import jinni_client
from core.watch.settings import WatchSettings

JINNI_CHILD = object()


def refuse_to_watch(settings: WatchSettings) -> None:
    raise OSError("no kernel log here")


async def test_a_watch_that_fails_to_start_is_reported_and_the_daemon_serves_on(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    stopped_children: list[object] = []
    served: list[bool] = []
    monkeypatch.setattr(api, "_on_printer", True)
    monkeypatch.setattr(jinni_client, "start_jinni", lambda: JINNI_CHILD)
    monkeypatch.setattr(jinni_client, "stop_jinni", stopped_children.append)
    monkeypatch.setattr(api.watch_runner, "start", refuse_to_watch)
    with caplog.at_level(logging.ERROR, logger="api"):
        async with api.lifespan(api.app):
            served.append(True)
    assert served == [True]
    assert "the printer is not watched" in caplog.text
    assert stopped_children == [JINNI_CHILD]
