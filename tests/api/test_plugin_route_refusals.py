# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the app is told when uninstall, deactivate or reconfigure is refused.

The app decides what the user sees from the status code and the detail shape alone, so these are the
contract, not an implementation detail: a plugin others depend on must come back as a 409 naming
those others (the app offers "remove them too"), a plugin that is not installed as a 404, and a
refusal that arrives while the printer is printing as a 409 the app turns into "not while printing".
An unexpected fault must not read as any of those, so it is a 422 and the app says so plainly.

Every plugin id here is made up; no package is installed and no device is touched.
"""
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from api import app
from core import access_requests, auth
from core import packages as package_ops
from core.packages.errors import BlockedActionError, DependentsError, MissingSettingError

_ISSUED_TOKEN = "fake-issued-token-0000"
_A_PLUGIN = "fake-camera"
_ITS_DEPENDENT = "fake-overlay"
_A_RESTART_MID_PRINT = "/etc/init.d/S55klipper restart"


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


@pytest.fixture
def app_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                             headers={"Authorization": f"Bearer {_ISSUED_TOKEN}"})


def _refusing(monkeypatch: pytest.MonkeyPatch, operation: str, refusal: Exception) -> None:
    def refuse(*sent: object, **named: object) -> Any:
        raise refusal
    monkeypatch.setattr(package_ops, operation, refuse)


async def test_uninstalling_a_plugin_others_depend_on_names_them_to_the_app(
    monkeypatch: pytest.MonkeyPatch, app_client: httpx.AsyncClient,
) -> None:
    _refusing(monkeypatch, "uninstall", DependentsError(_A_PLUGIN, [_ITS_DEPENDENT]))

    response = await app_client.delete(f"/plugins/{_A_PLUGIN}")

    assert response.status_code == 409
    assert response.json()["detail"] == {"error": "dependents", "plugin_id": _A_PLUGIN,
                                         "dependents": [_ITS_DEPENDENT]}


async def test_uninstalling_something_that_is_not_installed_is_a_not_found(
    monkeypatch: pytest.MonkeyPatch, app_client: httpx.AsyncClient,
) -> None:
    _refusing(monkeypatch, "uninstall", FileNotFoundError("no such plugin"))

    response = await app_client.delete(f"/plugins/{_A_PLUGIN}")

    assert response.status_code == 404


async def test_deactivating_a_plugin_others_depend_on_names_them_to_the_app(
    monkeypatch: pytest.MonkeyPatch, app_client: httpx.AsyncClient,
) -> None:
    _refusing(monkeypatch, "deactivate", DependentsError(_A_PLUGIN, [_ITS_DEPENDENT]))

    response = await app_client.post(f"/plugins/{_A_PLUGIN}/deactivate")

    assert response.status_code == 409
    assert response.json()["detail"]["dependents"] == [_ITS_DEPENDENT]


async def test_deactivating_while_the_printer_prints_names_the_blocked_actions(
    monkeypatch: pytest.MonkeyPatch, app_client: httpx.AsyncClient,
) -> None:
    """The plugin's own teardown would bounce Klipper, so the printer refuses mid print and the app
    tells the user which action it was."""
    _refusing(monkeypatch, "deactivate", BlockedActionError(frozenset({_A_RESTART_MID_PRINT})))

    response = await app_client.post(f"/plugins/{_A_PLUGIN}/deactivate")

    assert response.status_code == 409
    assert response.json()["detail"] == {"error": "blocked",
                                         "blocked_actions": [_A_RESTART_MID_PRINT]}


async def test_reconfiguring_without_a_required_setting_is_refused_not_half_applied(
    monkeypatch: pytest.MonkeyPatch, app_client: httpx.AsyncClient,
) -> None:
    _refusing(monkeypatch, "reconfigure", MissingSettingError(_A_PLUGIN, ["camera_device"]))

    response = await app_client.post(f"/plugins/{_A_PLUGIN}/reconfigure", json={})

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "missing_setting"


async def test_an_unexpected_fault_is_reported_as_itself_never_as_a_refusal(
    monkeypatch: pytest.MonkeyPatch, app_client: httpx.AsyncClient,
) -> None:
    """A fault the daemon did not anticipate must not wear a refusal's clothes: the app would tell
    the user to fix a dependency or a setting that was never the problem."""
    _refusing(monkeypatch, "reconfigure", RuntimeError("the disk went away"))

    response = await app_client.post(f"/plugins/{_A_PLUGIN}/reconfigure", json={})

    assert response.status_code == 422
    assert "RuntimeError" in response.json()["detail"]
