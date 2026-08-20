# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the app sees when a multi-plugin apply is refused, on both batch routes.

A batch is the one op that runs behind a live progress bar. If a refusal ends the run without
saying so on the progress feed, the app is left showing a bar that never finishes and the user has
no way to tell a refused install from a hung printer. These tests pin the refusal status, the
closing frame, and that the uploaded packages are wiped off the printer either way.

No package is ever really applied here: the apply step is replaced by the refusal under test.
"""
import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from api import app
from api.routes.feeds import install_hub
from core import access_requests, auth, packages

_ISSUED_TOKEN = "fake-issued-token-0000"
_A_RESTART_MID_PRINT = "/etc/init.d/S55klipper restart"
_BOTH_BATCH_ROUTES = [
    ("/packages/install-batch", "install_batch"),
    ("/packages/update-batch", "update_batch"),
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
    monkeypatch.delenv("BESPOK3D_DEV_OPEN", raising=False)


def _refusing(monkeypatch: pytest.MonkeyPatch, apply_step: str, refusal: Exception) -> None:
    def refuse(*sent: object, **named: object) -> Any:
        raise refusal
    monkeypatch.setattr(packages, apply_step, refuse)


async def _apply_two_packages(route: str) -> httpx.Response:
    uploads = [
        ("files", ("fake-camera.b3", b"fake package bytes", "application/octet-stream")),
        ("files", ("fake-overlay.b3", b"fake package bytes", "application/octet-stream")),
    ]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
    ) as client:
        return await client.post(
            route, files=uploads, data={"vars_json": ""},
            headers={"Authorization": f"Bearer {_ISSUED_TOKEN}"},
        )


async def _frames_seen_by_the_app(queue: asyncio.Queue[dict]) -> list[dict]:
    """Everything the progress feed carried, once the loop has run the pending deliveries."""
    await asyncio.sleep(0)
    return [queue.get_nowait() for _ in range(queue.qsize())]


@pytest.mark.parametrize(("route", "apply_step"), _BOTH_BATCH_ROUTES)
async def test_a_batch_refused_because_the_printer_is_printing_says_so(
    monkeypatch: pytest.MonkeyPatch, route: str, apply_step: str,
) -> None:
    _refusing(monkeypatch, apply_step,
              packages.BlockedActionError(frozenset({_A_RESTART_MID_PRINT})))

    response = await _apply_two_packages(route)

    assert response.status_code == 409
    assert response.json() == {"error": "blocked", "blocked_actions": [_A_RESTART_MID_PRINT]}


@pytest.mark.parametrize(("route", "apply_step"), _BOTH_BATCH_ROUTES)
async def test_a_package_the_printer_cannot_read_is_refused_as_a_bad_upload(
    monkeypatch: pytest.MonkeyPatch, route: str, apply_step: str,
) -> None:
    _refusing(monkeypatch, apply_step, ValueError("not a package"))

    response = await _apply_two_packages(route)

    assert response.status_code == 400
    assert response.json()["detail"] == "not a package"


@pytest.mark.parametrize(("route", "apply_step"), _BOTH_BATCH_ROUTES)
async def test_a_failure_nobody_foresaw_is_reported_by_its_kind_not_swallowed(
    monkeypatch: pytest.MonkeyPatch, route: str, apply_step: str,
) -> None:
    """The user gets a refusal naming what went wrong, so a bug reaches the report instead of
    looking like a plugin that applied fine."""
    _refusing(monkeypatch, apply_step, RuntimeError("the disk went away"))

    response = await _apply_two_packages(route)

    assert response.status_code == 422
    assert "RuntimeError: the disk went away" in response.json()["detail"]


@pytest.mark.parametrize(("route", "apply_step"), _BOTH_BATCH_ROUTES)
async def test_a_refused_batch_closes_the_progress_bar_instead_of_leaving_it_spinning(
    monkeypatch: pytest.MonkeyPatch, route: str, apply_step: str,
) -> None:
    _refusing(monkeypatch, apply_step, ValueError("not a package"))
    watching = install_hub.subscribe()

    await _apply_two_packages(route)

    assert (await _frames_seen_by_the_app(watching))[-1] == {"type": "done", "ok": False}
    install_hub.unsubscribe(watching)


@pytest.mark.parametrize(("route", "apply_step"), _BOTH_BATCH_ROUTES)
async def test_a_refused_batch_leaves_no_uploaded_packages_on_the_printer(
    monkeypatch: pytest.MonkeyPatch, route: str, apply_step: str,
) -> None:
    """The uploads land on a printer with very little free space, so a refusal that kept them would
    fill the disk one failed install at a time."""
    staged: list[Path] = []

    def refuse(base_vars: object, package_paths: list[Path], *sent: object, **named: object) -> Any:
        staged.extend(package_paths)
        raise ValueError("not a package")
    monkeypatch.setattr(packages, apply_step, refuse)

    await _apply_two_packages(route)

    assert [path.name for path in staged] == ["fake-camera.b3", "fake-overlay.b3"]
    assert not [path for path in staged if path.exists()]
