# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The app asks the printer to try a web address, and only an approved client may ask.

The try itself is replaced here; tests/core/test_web_reach.py covers it against a real server.
"""
import json
from pathlib import Path

import httpx
import pytest

from api import app
from api.routes import reach
from core import access_requests, auth

_ISSUED_TOKEN = "fake-issued-token-0000"
_TYPED_ADDRESS = "http://spoolman.fake:7912"


@pytest.fixture(autouse=True)
def daemon_acl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    acl = {
        "keys": ["fake-owner"], "roles": {"fake-owner": "admin"}, "labels": {"fake-owner": "Owner"},
        "tokens": [_ISSUED_TOKEN], "token_identity": {_ISSUED_TOKEN: "fake-owner"},
    }
    (tmp_path / "acl.json").write_text(json.dumps(acl))
    monkeypatch.setattr(auth, "ACL_PATH", tmp_path / "acl.json")
    monkeypatch.setattr(access_requests, "PENDING_PATH", tmp_path / "pending.json")
    monkeypatch.delenv("BESPOK3D_DEV_OPEN", raising=False)


def _daemon(token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                             headers={"Authorization": f"Bearer {token}"})


async def test_the_printer_reports_the_code_the_typed_address_answered_with(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tried: list[str] = []

    async def answers_not_found(url: str) -> int:
        tried.append(url)
        return 404
    monkeypatch.setattr(reach, "http_code_at", answers_not_found)

    async with _daemon(_ISSUED_TOKEN) as daemon:
        response = await daemon.post("/net/reach", json={"url": _TYPED_ADDRESS})

    assert response.status_code == 200
    assert response.json() == {"http_code": 404}
    assert tried == [_TYPED_ADDRESS]


async def test_the_printer_reports_no_answer_as_null(monkeypatch: pytest.MonkeyPatch) -> None:
    async def nothing_answers(url: str) -> None:
        return None
    monkeypatch.setattr(reach, "http_code_at", nothing_answers)

    async with _daemon(_ISSUED_TOKEN) as daemon:
        response = await daemon.post("/net/reach", json={"url": _TYPED_ADDRESS})

    assert response.json() == {"http_code": None}


async def test_a_client_without_a_valid_token_cannot_make_the_printer_fetch() -> None:
    async with _daemon("not-an-issued-token") as daemon:
        response = await daemon.post("/net/reach", json={"url": _TYPED_ADDRESS})

    assert response.status_code == 401
