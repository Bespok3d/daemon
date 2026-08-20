# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
import io
import json
import zipfile
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi import HTTPException, WebSocket
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from api import app
from api.routes import feeds as routes_feeds
from api.routes import health as routes_health
from api.routes.plugins import plugin_config
from core import (
    access_requests,
    auth,
    capabilities,
    jinni_client,
    packages,
    printer_identity,
)
from core.packages.integrity import ESCAPING_PLUGIN_ID, UNDECLARED_MEMBER
from version import DAEMON_VERSION


class _MockAdapter:
    def paths(self) -> dict[str, str]:
        return {}

TEST_TOKEN = "test-bearer-token-1234"


class _RecordingWebSocket:
    """Stands in for the app's socket on the refusal path, where a close code is the whole reply."""

    def __init__(self) -> None:
        self.close_code: int | None = None
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000) -> None:
        self.close_code = code


@pytest.fixture(autouse=True)
def test_acl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    acl = {
        "keys": ["owner-id"], "roles": {"owner-id": "admin"}, "labels": {"owner-id": "Owner"},
        "tokens": [TEST_TOKEN], "token_identity": {TEST_TOKEN: "owner-id"},
    }
    (tmp_path / "acl.json").write_text(json.dumps(acl))
    monkeypatch.setattr(auth, "ACL_PATH", tmp_path / "acl.json")
    monkeypatch.setattr(access_requests, "PENDING_PATH", tmp_path / "pending.json")


@pytest.fixture
def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    )


async def test_status_returns_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/status")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["version"] == "0.13.1"


async def test_status_reports_the_persisted_printer_uuid(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    identity_path = tmp_path / "printer_uuid"
    identity_path.write_text("11111111-2222-3333-4444-555555555555")
    monkeypatch.setattr(printer_identity, "IDENTITY_PATH", identity_path)
    response = await client.get("/status")
    assert response.json()["printer_uuid"] == "11111111-2222-3333-4444-555555555555"


async def test_status_printer_uuid_is_null_before_first_boot(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(printer_identity, "IDENTITY_PATH", tmp_path / "printer_uuid")
    response = await client.get("/status")
    assert response.json()["printer_uuid"] is None


async def test_oom_reports_no_kill_by_default(client: httpx.AsyncClient) -> None:
    response = await client.get("/oom")
    assert response.status_code == 200
    assert response.json() == {"kills": 0, "token": "", "detail": ""}


async def test_oom_relays_a_kill_for_the_app_to_localize(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from protocol import OomReport
    from tests.fakes_generic import FakeGenericJinni

    class _OomJinni(FakeGenericJinni):
        def oom_report(self) -> OomReport:
            return OomReport(kills=1, token="oom-kill",
                             detail="the kernel killed process (python3)")
    oom_jinni = _OomJinni()
    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", lambda: oom_jinni)
    body = (await client.get("/oom")).json()
    assert body["kills"] == 1
    assert body["token"] == "oom-kill"
    assert "python3" in body["detail"]


async def test_capabilities_returns_all_required_fields(client: httpx.AsyncClient) -> None:
    response = await client.get("/capabilities")
    assert response.status_code == 200

    body = response.json()
    assert "adapter" in body
    assert "hardware" in body
    assert "installed" in body
    assert "arch" in body
    assert "board_class" in body
    assert body["kernel"] == {"release": "6.1.99", "vermagic": "6.1.99 SMP preempt mod_unload aarch64"}  # noqa: E501
    assert "klipper_version" in body
    assert "preferred_registries" in body
    assert "endpoints" in body


async def test_capabilities_reports_which_plugins_kept_their_signature(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Presence on disk only: it says the package carried a signature, never that it verified.
    signed = tmp_path / "plugins" / "spoolman"
    signed.mkdir(parents=True)
    (signed / "manifest.json.sig").write_text("-----BEGIN PGP SIGNATURE-----")
    (tmp_path / "plugins" / "camera").mkdir()
    monkeypatch.setattr(capabilities, "PLUGIN_ROOT", tmp_path / "plugins")

    body = (await client.get("/capabilities")).json()
    assert body["stored_signatures"] == ["spoolman"]


async def test_capabilities_installed_is_a_dict(client: httpx.AsyncClient) -> None:
    response = await client.get("/capabilities")
    body = response.json()
    assert isinstance(body["installed"], dict)


async def test_capabilities_hardware_is_a_list(client: httpx.AsyncClient) -> None:
    response = await client.get("/capabilities")
    body = response.json()
    assert isinstance(body["hardware"], list)


async def test_capabilities_preferred_registries_is_a_list(client: httpx.AsyncClient) -> None:
    response = await client.get("/capabilities")
    body = response.json()
    assert isinstance(body["preferred_registries"], list)


@pytest.fixture
def unauthed_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    )


async def test_request_without_authorization_header_gets_401(
    unauthed_client: httpx.AsyncClient,
) -> None:
    response = await unauthed_client.get("/status")
    assert response.status_code == 401


async def test_request_with_wrong_token_gets_401(
    unauthed_client: httpx.AsyncClient,
) -> None:
    response = await unauthed_client.get(
        "/status", headers={"Authorization": "Bearer wrong-token"}
    )
    assert response.status_code == 401


async def test_docs_endpoint_accessible_without_auth(
    unauthed_client: httpx.AsyncClient,
) -> None:
    response = await unauthed_client.get("/docs")
    assert response.status_code == 200


async def test_license_offer_is_reachable_without_a_token(
    unauthed_client: httpx.AsyncClient,
) -> None:
    response = await unauthed_client.get("/license")
    assert response.status_code == 200


async def test_license_offer_names_the_running_version_and_its_source(
    client: httpx.AsyncClient,
) -> None:
    body = (await client.get("/license")).json()
    assert body["version"] == DAEMON_VERSION
    assert body["license"] == "AGPL-3.0-or-later"
    assert body["source"] == "https://github.com/Bespok3d/daemon"
    assert DAEMON_VERSION in body["notice"]
    assert "or any later version" in body["notice"]


def _noop_vars(_: dict[str, str]) -> None:
    pass


def _minimal_b3() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"name": "test-plugin"}))
    return buf.getvalue()


async def test_deactivate_returns_ok(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", _MockAdapter)
    monkeypatch.setattr(packages, "deactivate_all", _noop_vars)
    response = await client.post("/deactivate")
    assert response.status_code == 200
    assert response.json()["ok"] is True


async def test_teardown_returns_ok(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", _MockAdapter)
    monkeypatch.setattr(packages, "teardown", _noop_vars)
    response = await client.post("/teardown")
    assert response.status_code == 200
    assert response.json()["ok"] is True


async def test_selfcheck_returns_ok_true_when_no_drift(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", _MockAdapter)
    monkeypatch.setattr(routes_health, "run_selfcheck",
                        lambda _vars: {"switched_off": False, "reboot_required": [],
                                       "problems": [], "drift": []})
    response = await client.get("/selfcheck")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["problems"] == []
    assert body["drift"] == []


async def test_selfcheck_returns_ok_false_with_drift_details(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected_path = (
        "/userdata/bespok3d/usr/local/plugins/camera-hw-accel/files/camera.py"
    )
    sample_drift = [
        {
            "plugin_id": "camera-hw-accel",
            "symlink_issues": [
                {
                    "kind": "missing",
                    "link_path": "/home/lava/klipper/klippy/extras/camera.py",
                    "expected_target": expected_path,
                }
            ],
        }
    ]
    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", _MockAdapter)
    drifted = {"switched_off": False, "reboot_required": [], "problems": [], "drift": sample_drift}
    monkeypatch.setattr(routes_health, "run_selfcheck", lambda _vars: drifted)
    response = await client.get("/selfcheck")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert len(body["drift"]) == 1
    assert body["drift"][0]["plugin_id"] == "camera-hw-accel"
    assert body["drift"][0]["symlink_issues"][0]["kind"] == "missing"


async def test_selfcheck_relays_what_the_printer_says_needs_a_power_cycle(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The printer names its own states that no restart clears; the daemon relays the tokens
    untouched. A printer asking for a power cycle is still sound, so ok stays true: a caller shows
    the reason and offers the reboot, and it is never a problem to fix."""
    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", _MockAdapter)
    wedged = {"switched_off": False, "reboot_required": ["display-pipe-wedged"],
              "problems": [], "drift": []}
    monkeypatch.setattr(routes_health, "run_selfcheck", lambda _vars: wedged)
    response = await client.get("/selfcheck")
    assert response.status_code == 200
    body = response.json()
    assert body["reboot_required"] == ["display-pipe-wedged"]
    assert body["ok"] is True


async def test_install_route_returns_ok(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_install(
        _path: Path, _all_vars: dict[str, str], user_vars: dict[str, str] | None = None,
        on_phase: object = None,
    ) -> tuple[str, list]:
        return "test-plugin", []

    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", _MockAdapter)
    monkeypatch.setattr(packages, "install", fake_install)
    response = await client.post(
        "/plugins/install",
        files={"file": ("plugin.b3", _minimal_b3(), "application/octet-stream")},
        data={"vars_json": "{}"},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["plugin_id"] == "test-plugin"


async def test_install_route_returns_409_on_unmet_requirement(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_requirement(*_args: object, **_kwargs: object) -> tuple[str, list]:
        raise packages.RequirementError("zerotier", ["tun"])

    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", _MockAdapter)
    monkeypatch.setattr(packages, "install", raise_requirement)
    response = await client.post(
        "/plugins/install",
        files={"file": ("zerotier.b3", _minimal_b3(), "application/octet-stream")},
        data={"vars_json": "{}"},
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error"] == "requirement"
    assert detail["missing"] == ["tun"]


async def test_install_route_returns_409_naming_the_refused_members(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A refused package is not a malformed request: it gets the same 409 refusal family the app
    # already discriminates on, carrying the reason token and the members that earned it.
    def raise_integrity(*_args: object, **_kwargs: object) -> tuple[str, list]:
        raise packages.IntegrityError("stowaway", UNDECLARED_MEMBER, ["files/extra.sh"])

    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", _MockAdapter)
    monkeypatch.setattr(packages, "install", raise_integrity)
    response = await client.post(
        "/plugins/install",
        files={"file": ("stowaway.b3", _minimal_b3(), "application/octet-stream")},
        data={"vars_json": "{}"},
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error"] == "integrity"
    assert detail["plugin_id"] == "stowaway"
    assert detail["reason"] == UNDECLARED_MEMBER
    assert detail["paths"] == ["files/extra.sh"]


async def test_install_route_returns_400_on_bad_vars(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", _MockAdapter)
    response = await client.post(
        "/plugins/install",
        files={"file": ("plugin.b3", b"", "application/octet-stream")},
        data={"vars_json": json.dumps({"NAME": "bad<value>"})},
    )
    assert response.status_code == 400
    assert "allows only" in response.json()["detail"]


async def test_install_route_takes_a_number_or_a_toggle_as_a_setting(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A manifest declares a field's type, and a `number` field's 5 or a `toggle` field's true is
    how JSON writes what those types mean, so the app sends them unquoted. The printer takes them
    and writes them into the plugin's config as text."""
    settings_installed: dict[str, str] = {}

    def record_user_vars(
        _path: Path, _all_vars: dict[str, str], user_vars: dict[str, str] | None = None,
        on_phase: object = None,
    ) -> tuple[str, list]:
        settings_installed.update(user_vars or {})
        return "filaman", []

    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", _MockAdapter)
    monkeypatch.setattr(packages, "install", record_user_vars)
    response = await client.post(
        "/plugins/install",
        files={"file": ("filaman.b3", _minimal_b3(), "application/octet-stream")},
        data={"vars_json": json.dumps(
            {"SYNC_RATE": 5, "DEFAULT_DENSITY": 1.24, "REPUSH_ON_STARTUP": True}
        )},
    )
    assert response.status_code == 200
    assert settings_installed == {
        "SYNC_RATE": "5", "DEFAULT_DENSITY": "1.24", "REPUSH_ON_STARTUP": "true",
    }


async def test_reconfigure_route_takes_a_number_as_a_setting(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_written: dict[str, str] = {}

    def record_user_vars(
        plugin_id: str, _all_vars: dict[str, str], user_vars: dict[str, str]
    ) -> tuple[str, list]:
        settings_written.update(user_vars)
        return plugin_id, []

    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", _MockAdapter)
    monkeypatch.setattr(packages, "reconfigure", record_user_vars)
    response = await client.post("/plugins/filaman/reconfigure", json={"SYNC_RATE": 5})
    assert response.status_code == 200
    assert settings_written == {"SYNC_RATE": "5"}


async def test_reconfigure_route_still_takes_a_quoted_setting(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every plugin shipping today writes its settings quoted, so the quoted value has to reach the
    plugin exactly as it was sent, unchanged by the rendering that lets an unquoted one through."""
    settings_written: dict[str, str] = {}

    def record_user_vars(
        plugin_id: str, _all_vars: dict[str, str], user_vars: dict[str, str]
    ) -> tuple[str, list]:
        settings_written.update(user_vars)
        return plugin_id, []

    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", _MockAdapter)
    monkeypatch.setattr(packages, "reconfigure", record_user_vars)
    response = await client.post(
        "/plugins/spoolman/reconfigure",
        json={"SPOOLMAN_SERVER": "printer.local:7912", "SYNC_RATE": "5", "REPUSH": "true"},
    )
    assert response.status_code == 200
    assert settings_written == {
        "SPOOLMAN_SERVER": "printer.local:7912", "SYNC_RATE": "5", "REPUSH": "true",
    }


async def test_recover_route_returns_ok(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    given_progress_sinks: list[packages.ProgressSink | None] = []

    def recover_without_plugins(
        _vars: dict[str, str], publish_progress: packages.ProgressSink | None = None
    ) -> list[dict]:
        given_progress_sinks.append(publish_progress)

        return []

    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", _MockAdapter)
    monkeypatch.setattr(packages, "recover", recover_without_plugins)
    response = await client.post("/packages/recover")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["results"] == []
    # Recovery reports each plugin as it goes, so the route must hand it the live progress feed.
    assert given_progress_sinks == [routes_feeds.install_hub.publish]


async def test_recover_route_reports_a_top_level_fault_as_422_not_500(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A top-level recover fault (e.g. the closing restart cannot reach the jinni) must surface as a
    # reported error, never a contentless 500 (printer-never-broken: act or report).
    def boom(
        _vars: dict[str, str], _publish_progress: packages.ProgressSink | None = None
    ) -> list:
        raise RuntimeError("no reply from the jinni for 'write_files'")

    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", _MockAdapter)
    monkeypatch.setattr(packages, "recover", boom)
    response = await client.post("/packages/recover")
    assert response.status_code == 422
    assert "no reply from the jinni" in response.json()["detail"]


async def test_update_batch_route_returns_per_plugin_results(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_update_batch(
        _vars: dict[str, str], _paths: list[Path], _vars_by_id: dict[str, dict[str, str]],
        _publish: object = None,
    ) -> list[dict]:
        return [
            {"plugin_id": "alpha", "ok": True, "skipped": False, "reason": "", "log": []},
            {"plugin_id": "(services)", "ok": True, "skipped": False, "reason": "", "log": []},
        ]

    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", _MockAdapter)
    monkeypatch.setattr(packages, "update_batch", fake_update_batch)
    response = await client.post(
        "/packages/update-batch",
        files=[
            ("files", ("alpha.b3", _minimal_b3(), "application/octet-stream")),
            ("files", ("beta.b3", _minimal_b3(), "application/octet-stream")),
        ],
        data={"vars_json": json.dumps({"alpha": {"SPOOLMAN_SERVER": "printer.local"}})},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert [result["plugin_id"] for result in body["results"]] == ["alpha", "(services)"]


async def test_update_batch_route_settles_a_bad_setting_per_plugin(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A value the printer will not take costs its own plugin, never the whole call: the route hands
    every package to the batch, which leaves that one out and installs the rest. It also hands over
    each package under the name the app uploaded, so a package too broken to name itself is still
    reported as the plugin the user picked."""
    staged: list[str] = []

    def record_paths(
        _vars: dict[str, str], paths: list[Path], _vars_by_id: dict[str, dict[str, str]],
        _publish: object = None,
    ) -> list[dict]:
        staged.extend(path.name for path in paths)
        return [{"plugin_id": "alpha", "ok": False, "skipped": True,
                 "reason": "allows only", "log": []}]

    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", _MockAdapter)
    monkeypatch.setattr(packages, "update_batch", record_paths)
    response = await client.post(
        "/packages/update-batch",
        files=[("files", ("alpha.b3", _minimal_b3(), "application/octet-stream"))],
        data={"vars_json": json.dumps({"alpha": {"NAME": "bad<value>"}})},
    )
    assert response.status_code == 200
    assert staged == ["alpha.b3"]
    assert response.json()["results"][0]["skipped"] is True


async def test_update_batch_route_takes_a_number_as_a_setting(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_by_plugin: dict[str, dict[str, str]] = {}

    def record_vars_by_id(
        _vars: dict[str, str], _paths: list[Path], vars_by_id: dict[str, dict[str, str]],
        _publish: object = None,
    ) -> list[dict]:
        settings_by_plugin.update(vars_by_id)
        return [{"plugin_id": "alpha", "ok": True, "skipped": False, "reason": "", "log": []}]

    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", _MockAdapter)
    monkeypatch.setattr(packages, "update_batch", record_vars_by_id)
    response = await client.post(
        "/packages/update-batch",
        files=[("files", ("alpha.b3", _minimal_b3(), "application/octet-stream"))],
        data={"vars_json": json.dumps({"alpha": {"SYNC_RATE": 5, "REPUSH_ON_STARTUP": False}})},
    )
    assert response.status_code == 200
    assert settings_by_plugin == {"alpha": {"SYNC_RATE": "5", "REPUSH_ON_STARTUP": "false"}}


async def test_install_batch_route_returns_per_plugin_results(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_install_batch(
        _vars: dict[str, str], _paths: list[Path], _vars_by_id: dict[str, dict[str, str]],
        _publish: object = None,
    ) -> list[dict]:
        return [
            {"plugin_id": "camera", "ok": True, "skipped": False, "reason": "", "log": []},
            {"plugin_id": "(services)", "ok": True, "skipped": False, "reason": "", "log": []},
        ]

    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", _MockAdapter)
    monkeypatch.setattr(packages, "install_batch", fake_install_batch)
    response = await client.post(
        "/packages/install-batch",
        files=[
            ("files", ("camera.b3", _minimal_b3(), "application/octet-stream")),
            ("files", ("screen.b3", _minimal_b3(), "application/octet-stream")),
        ],
        data={"vars_json": json.dumps({})},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert [result["plugin_id"] for result in body["results"]] == ["camera", "(services)"]


async def test_install_batch_route_reports_a_plugin_left_out_alongside_the_ones_installed(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plugin the printer will not accept comes back as its own row saying why, in a normal
    results envelope, so the user still gets every other plugin in the same pick."""
    def settle_per_plugin(*_args: object, **_kwargs: object) -> list[dict]:
        return [
            {"plugin_id": "camera", "ok": True, "skipped": False, "reason": "", "log": []},
            {
                "plugin_id": "force-bed-mesh-adaptive", "ok": False, "skipped": True,
                "reason": "Conflicts with installed plugin(s): force-bed-mesh", "log": [],
            },
        ]

    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", _MockAdapter)
    monkeypatch.setattr(packages, "install_batch", settle_per_plugin)
    response = await client.post(
        "/packages/install-batch",
        files=[
            ("files", ("camera.b3", _minimal_b3(), "application/octet-stream")),
            ("files", ("force-bed-mesh-adaptive.b3", _minimal_b3(), "application/octet-stream")),
        ],
        data={"vars_json": json.dumps({})},
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert [(entry["plugin_id"], entry["skipped"]) for entry in results] == [
        ("camera", False), ("force-bed-mesh-adaptive", True),
    ]
    assert results[1]["reason"] == "Conflicts with installed plugin(s): force-bed-mesh"


async def test_uninstall_route_returns_ok(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_uninstall(_plugin_id: str, _vars: dict[str, str], cascade: bool = False) -> list[str]:
        return ["my-plugin"]

    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", _MockAdapter)
    monkeypatch.setattr(packages, "uninstall", fake_uninstall)
    response = await client.delete("/plugins/my-plugin")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["removed"] == ["my-plugin"]


async def test_uninstalling_a_plugin_that_is_already_gone_is_not_an_error(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Removing something that is not there has already reached the state the caller asked for.
    # A retry after a removal that died partway must converge, not hand back an error nobody
    # can act on.
    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", _MockAdapter)
    response = await client.delete("/plugins/missing-plugin")
    assert response.status_code == 200
    assert response.json()["removed"] == []


def _seed_installed_plugin(
    plugin_root: Path, plugin_id: str, user_vars: dict[str, str] | None = None
) -> None:
    plugin_dir = plugin_root / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(json.dumps({"name": plugin_id}))
    if user_vars:
        (plugin_dir / packages.USER_VARS_FILE).write_text(json.dumps(user_vars))


async def test_plugin_config_returns_the_persisted_user_vars(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    _seed_installed_plugin(tmp_path, "spoolman", {"SPOOLMAN_SERVER": "http://spoolman.example:7912"})
    response = await client.get("/plugins/spoolman/config")
    assert response.status_code == 200
    assert response.json() == {"vars": {"SPOOLMAN_SERVER": "http://spoolman.example:7912"}}


async def test_plugin_config_is_empty_for_a_var_less_plugin(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    _seed_installed_plugin(tmp_path, "cpu-temp")
    response = await client.get("/plugins/cpu-temp/config")
    assert response.status_code == 200
    assert response.json() == {"vars": {}}


async def test_plugin_config_returns_404_for_an_unknown_plugin(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    response = await client.get("/plugins/ghost/config")
    assert response.status_code == 404


async def test_plugin_config_refuses_an_id_that_climbs_out_of_the_plugin_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Driven at the handler because the route's `[^/]+` param accepts an id whose separators arrived
    # percent-encoded, and the test client decodes them before routing sees them.
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path / "plugins")

    with pytest.raises(HTTPException) as refusal:
        await plugin_config("../../etc")

    assert refusal.value.status_code == 409
    assert refusal.value.detail == {
        "error": "integrity", "plugin_id": "../../etc",
        "reason": "escaping_plugin_id", "paths": ["../../etc"],
    }


async def test_plugin_config_requires_auth(unauthed_client: httpx.AsyncClient) -> None:
    response = await unauthed_client.get("/plugins/spoolman/config")
    assert response.status_code == 401


async def test_uninstall_batch_route_returns_per_plugin_results(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_uninstall_batch(
        _plugin_ids: list[str], _vars: dict[str, str], cascade: bool = False
    ) -> list[dict]:
        return [
            {"plugin_id": "alpha", "ok": True, "skipped": False, "reason": "", "log": []},
            {"plugin_id": "(services)", "ok": True, "skipped": False, "reason": "", "log": []},
        ]

    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", _MockAdapter)
    monkeypatch.setattr(packages, "uninstall_batch", fake_uninstall_batch)
    response = await client.post(
        "/packages/uninstall-batch", json={"plugin_ids": ["alpha"], "cascade": False}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert [result["plugin_id"] for result in body["results"]] == ["alpha", "(services)"]


async def test_uninstall_batch_route_returns_409_on_dependents(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_dependents(_plugin_ids: list[str], _vars: dict[str, str], cascade: bool = False) -> None:  # noqa: E501
        raise packages.DependentsError("rfid", ["spoolman"])

    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", _MockAdapter)
    monkeypatch.setattr(packages, "uninstall_batch", raise_dependents)
    response = await client.post(
        "/packages/uninstall-batch", json={"plugin_ids": ["rfid"], "cascade": False}
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error"] == "dependents"
    assert detail["dependents"] == ["spoolman"]


async def test_deactivate_route_returns_the_dependents_refusal_the_app_renders(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The shipped app reads this exact body to say "Still needed by: spoolman"; a different shape
    # reaches the user as a raw error blob.
    def raise_dependents(_plugin_id: str, _vars: dict[str, str], cascade: bool = False) -> list[str]:  # noqa: E501
        raise packages.DependentsError("rfid", ["spoolman"])

    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", _MockAdapter)
    monkeypatch.setattr(packages, "deactivate", raise_dependents)
    response = await client.post("/plugins/rfid/deactivate")

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error"] == "dependents"
    assert detail["plugin_id"] == "rfid"
    assert detail["dependents"] == ["spoolman"]


async def test_deactivate_route_with_cascade_reports_every_plugin_it_took_off(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def deactivate_both(plugin_id: str, _vars: dict[str, str], cascade: bool = False) -> list[str]:
        return ["spoolman", plugin_id] if cascade else [plugin_id]

    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", _MockAdapter)
    monkeypatch.setattr(packages, "deactivate", deactivate_both)
    response = await client.post("/plugins/rfid/deactivate?cascade=true")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "deactivated": ["spoolman", "rfid"]}


def _anon() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_access_request_is_unauthenticated_and_stores_pending(
    client: httpx.AsyncClient,
) -> None:
    async with _anon() as anon:
        response = await anon.post(
            "/access/request",
            json={"identity": "laptop-b", "label": "Laptop B", "token": "newtoken00000000"},
        )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    listed = await client.get("/access/clients")
    assert any(item["identity"] == "laptop-b" for item in listed.json()["pending"])


async def test_access_clients_never_exposes_tokens(client: httpx.AsyncClient) -> None:
    async with _anon() as anon:
        await anon.post(
            "/access/request",
            json={"identity": "laptop-b", "label": "Laptop B", "token": "newtoken00000000"},
        )
    response = await client.get("/access/clients")
    assert response.status_code == 200
    assert TEST_TOKEN not in response.text
    assert "newtoken00000000" not in response.text


async def test_access_grant_then_revoke(client: httpx.AsyncClient) -> None:
    async with _anon() as anon:
        await anon.post(
            "/access/request",
            json={"identity": "laptop-b", "label": "Laptop B", "token": "newtoken00000000"},
        )
    grant = await client.post("/access/grant", json={"identity": "laptop-b"})
    assert grant.status_code == 200
    assert auth.is_authorized_token("newtoken00000000")
    revoke = await client.post("/access/revoke", json={"identity": "laptop-b"})
    assert revoke.status_code == 200
    assert not auth.is_authorized_token("newtoken00000000")


async def test_access_grant_unknown_pending_is_404(client: httpx.AsyncClient) -> None:
    response = await client.post("/access/grant", json={"identity": "ghost"})
    assert response.status_code == 404


async def test_access_request_rejects_a_malicious_identity() -> None:
    async with _anon() as anon:
        response = await anon.post(
            "/access/request",
            json={"identity": "evil;rm -rf /", "label": "x", "token": "a" * 64},
        )
    assert response.status_code == 400


def _seed_plugin_with_log(plugin_root: Path, line: str) -> None:
    plugin_dir = plugin_root / "octoeverywhere"
    plugin_dir.mkdir(parents=True)
    manifest = {"name": "octoeverywhere", "log": {"path": "oe.log"}}
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest))
    (plugin_dir / "oe.log").write_text(line)


def test_install_progress_ws_rejects_bad_token() -> None:
    with pytest.raises(WebSocketDisconnect):
        with TestClient(app).websocket_connect("/ws/install-progress?token=wrong") as ws:
            ws.receive_json()


def test_install_progress_ws_replays_active_run_then_streams_done() -> None:
    # The app opens the socket just before the install POST, so the run is ACTIVE on connect: the
    # buffered phase replays, then the terminal done streams live. A socket opened AFTER a run
    # finished must replay nothing (the duplicate-steps fix), a contract covered at the hub layer in
    # test_install_progress.py. Asserting replay of a FINISHED run here (the old test) made the
    # server send nothing, so receive_json() blocked forever and hung the whole suite.
    routes_feeds.install_hub.begin()
    routes_feeds.install_hub._deliver({"type": "phase", "phase": {"id": "extract"}})
    url = f"/ws/install-progress?token={TEST_TOKEN}"
    with TestClient(app).websocket_connect(url) as ws:
        replayed = ws.receive_json()
        routes_feeds.install_hub.publish({"type": "done", "ok": True})
        streamed = ws.receive_json()
    assert replayed == {"type": "phase", "phase": {"id": "extract"}}
    assert streamed == {"type": "done", "ok": True}


def test_plugin_log_ws_rejects_bad_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    _seed_plugin_with_log(tmp_path, "link https://oe.example/x\n")
    with pytest.raises(WebSocketDisconnect):
        with TestClient(app).websocket_connect("/ws/plugin-log/octoeverywhere?token=wrong") as ws:
            ws.receive_json()


def test_plugin_log_ws_unknown_plugin_closes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    url = f"/ws/plugin-log/ghost?token={TEST_TOKEN}"
    with pytest.raises(WebSocketDisconnect):
        with TestClient(app).websocket_connect(url) as ws:
            ws.receive_json()


def test_the_plugin_log_source_refuses_an_id_that_climbs_out_of_the_plugin_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    # A real tailable plugin sits at the escaped location, so an unguarded resolver would hand back
    # its log instead of refusing: the refusal is what this asserts, not the absence of a target.
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    monkeypatch.setattr(packages, "PLUGIN_ROOT", plugin_root)
    _seed_plugin_with_log(tmp_path, "link https://oe.example/x\n")

    with pytest.raises(packages.IntegrityError) as refusal:
        routes_feeds._plugin_log_source("../octoeverywhere", "")

    assert refusal.value.reason == ESCAPING_PLUGIN_ID


async def test_plugin_log_ws_closes_on_an_id_that_climbs_out_of_the_plugin_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    # Driven at the handler because the route's `[^/]+` param accepts an id whose separators arrived
    # percent-encoded, and the test client decodes them before routing sees them. The escaped
    # location holds a tailable plugin, so an unguarded handler would accept and start streaming it.
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    monkeypatch.setattr(packages, "PLUGIN_ROOT", plugin_root)
    _seed_plugin_with_log(tmp_path, "link https://oe.example/x\n")
    refused = _RecordingWebSocket()

    await routes_feeds.plugin_log_feed(
        cast(WebSocket, refused), "../octoeverywhere", token=TEST_TOKEN,
    )

    assert refused.close_code == 1008
    assert not refused.accepted


def test_plugin_log_ws_streams_snapshot_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    _seed_plugin_with_log(tmp_path, "ready https://octoeverywhere.com/getstarted?code=XYZ\n")
    url = f"/ws/plugin-log/octoeverywhere?token={TEST_TOKEN}"
    with TestClient(app).websocket_connect(url) as ws:
        event = ws.receive_json()
    assert event == {
        "value": "https://octoeverywhere.com/getstarted?code=XYZ",
        "pattern": "url",
    }
