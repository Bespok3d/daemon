import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from api import app
from api.routes import feeds as routes_feeds
from api.routes import health as routes_health
from core import auth, jinni_client, packages


class _MockAdapter:
    def paths(self) -> dict[str, str]:
        return {}

TEST_TOKEN = "test-bearer-token-1234"


@pytest.fixture(autouse=True)
def test_acl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    acl = {
        "keys": ["owner-id"], "roles": {"owner-id": "admin"}, "labels": {"owner-id": "Owner"},
        "tokens": [TEST_TOKEN], "token_identity": {TEST_TOKEN: "owner-id"},
    }
    (tmp_path / "acl.json").write_text(json.dumps(acl))
    monkeypatch.setattr(auth, "ACL_PATH", tmp_path / "acl.json")
    monkeypatch.setattr(auth, "PENDING_PATH", tmp_path / "pending.json")


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
    assert body["version"] == "0.12.11-dev"


async def test_capabilities_returns_all_required_fields(client: httpx.AsyncClient) -> None:
    response = await client.get("/capabilities")
    assert response.status_code == 200

    body = response.json()
    assert "adapter" in body
    assert "hardware" in body
    assert "installed" in body
    assert "klipper_version" in body
    assert "preferred_registries" in body
    assert "endpoints" in body


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
    monkeypatch.setattr(routes_health, "run_selfcheck", lambda _vars: [])
    response = await client.get("/selfcheck")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
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
    monkeypatch.setattr(routes_health, "run_selfcheck", lambda _vars: sample_drift)
    response = await client.get("/selfcheck")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert len(body["drift"]) == 1
    assert body["drift"][0]["plugin_id"] == "camera-hw-accel"
    assert body["drift"][0]["symlink_issues"][0]["kind"] == "missing"


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


async def test_recover_route_returns_ok(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", _MockAdapter)
    monkeypatch.setattr(packages, "recover", lambda _vars: [])
    response = await client.post("/packages/recover")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["results"] == []


async def test_recover_route_reports_a_top_level_fault_as_422_not_500(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A top-level recover fault (e.g. the closing restart cannot reach the jinni) must surface as a
    # reported error, never a contentless 500 (printer-never-broken: act or report).
    def boom(_vars: dict[str, str]) -> list:
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


async def test_update_batch_route_returns_400_on_bad_vars(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", _MockAdapter)
    response = await client.post(
        "/packages/update-batch",
        files=[("files", ("alpha.b3", _minimal_b3(), "application/octet-stream"))],
        data={"vars_json": json.dumps({"alpha": {"NAME": "bad<value>"}})},
    )
    assert response.status_code == 400
    assert "allows only" in response.json()["detail"]


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


async def test_install_batch_route_returns_409_on_conflict(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_conflict(*_args: object, **_kwargs: object) -> list[dict]:
        raise packages.ConflictError("force-bed-mesh", ["force-bed-mesh-adaptive"])

    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", _MockAdapter)
    monkeypatch.setattr(packages, "install_batch", raise_conflict)
    response = await client.post(
        "/packages/install-batch",
        files=[("files", ("force-bed-mesh.b3", _minimal_b3(), "application/octet-stream"))],
        data={"vars_json": json.dumps({})},
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error"] == "conflict"
    assert detail["conflicts"] == ["force-bed-mesh-adaptive"]


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


async def test_uninstall_route_returns_404_when_plugin_missing(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_not_found(plugin_id: str, _vars: dict[str, str], cascade: bool = False) -> None:
        raise FileNotFoundError(plugin_id)

    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", _MockAdapter)
    monkeypatch.setattr(packages, "uninstall", raise_not_found)
    response = await client.delete("/plugins/missing-plugin")
    assert response.status_code == 404


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
