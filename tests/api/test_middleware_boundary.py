# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Refusal test for api/middleware.py: the request boundary every app call passes through.

Requirement: BearerTokenMiddleware must refuse (401) any request whose path is not byte
identical to one of the exempt paths (/docs, /redoc, /openapi.json, /access/request,
/license) and whose Authorization header does not carry a Bearer token issued in the ACL.

If the exempt check were ever loosened from an exact match to a prefix match, a path that
merely starts with an exempt path would slip through unauthenticated. This test pins the
exact-match boundary so that regression cannot land silently.
"""
import json
from pathlib import Path

import httpx
import pytest

from api import app
from core import access_requests, auth

_ISSUED_TOKEN = "fake-issued-token-0000"

_NEAR_MISS_PATHS = [
    "/access/requestx",
    "/access/request/extra",
    "/license2",
    "/license/",
    "/docs2",
    "/redoc2",
    "/openapi.json.bak",
]


@pytest.fixture(autouse=True)
def daemon_acl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    acl = {
        "keys": ["fake-owner"], "roles": {"fake-owner": "admin"}, "labels": {"fake-owner": "Owner"},
        "tokens": [_ISSUED_TOKEN], "token_identity": {_ISSUED_TOKEN: "fake-owner"},
    }
    (tmp_path / "acl.json").write_text(json.dumps(acl))
    monkeypatch.setattr(auth, "ACL_PATH", tmp_path / "acl.json")
    monkeypatch.setattr(access_requests, "PENDING_PATH", tmp_path / "pending.json")
    # Pin dev-open off so this boundary test never rides on a stray environment setting.
    monkeypatch.delenv("BESPOK3D_DEV_OPEN", raising=False)


@pytest.fixture
def unauthed_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.parametrize("near_miss_path", _NEAR_MISS_PATHS)
async def test_path_sharing_an_exempt_prefix_still_requires_a_token(
    unauthed_client: httpx.AsyncClient, near_miss_path: str
) -> None:
    response = await unauthed_client.get(near_miss_path)
    assert response.status_code == 401


async def test_empty_bearer_token_on_a_protected_route_is_refused(
    unauthed_client: httpx.AsyncClient,
) -> None:
    response = await unauthed_client.get("/status", headers={"Authorization": "Bearer "})
    assert response.status_code == 401
