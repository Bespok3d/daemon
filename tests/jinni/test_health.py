"""The klipper printer jinni judges its own health and reports it as one DeviceHealth (ADR-0037).

`health()` is the single verb the daemon's safety net asks for. It probes each service over its
auth-free Unix socket (so it survives the moonraker-auth plugin's force_logins) with an HTTP
fallback, and folds in the stock MQTT broker. The retry loops + /server/info parsing are the pure
functions `klipper_healthy` / `probe_moonraker` / `_parse_server_info`, exercised directly here; the
assembly into a report is exercised through `health()`.
"""
import urllib.error
import urllib.request
from collections.abc import Callable
from email.message import Message
from typing import NoReturn

import pytest

from jinni import health, inspection
from jinni.contracts import KLIPPER_SERVICE, MOONRAKER_SERVICE
from jinni.health import MoonrakerInfo
from jinni.klipper import KLIPPER_PATH_KEYS, KlipperPrinterJinni

MP = pytest.MonkeyPatch


def _probe(up: bool, body: str) -> Callable[[str], tuple[bool, str]]:
    return lambda _url: (up, body)


def test_klipper_healthy_prefers_the_api_socket(monkeypatch: MP) -> None:
    # Klipper's API socket is auth-free, so it is the source of truth even when Moonraker forces
    # logins; the HTTP probe is only the fallback when the socket is unavailable.
    monkeypatch.setattr(health.klippy, "query_klippy_state", lambda _path: "ready")
    ready, detail = health.klipper_healthy("/tmp/klippy.sock", _probe(False, ""))
    assert ready is True
    assert "api socket" in detail


def test_klipper_healthy_falls_back_to_http_without_a_socket() -> None:
    ready, detail = health.klipper_healthy("", _probe(True, "via http"))
    assert ready is True
    assert detail == "via http"


def test_probe_moonraker_reads_force_logins_401_as_up(monkeypatch: MP) -> None:
    # moonraker-auth turns on force_logins, so /server/info answers 401: the server up and demanding
    # a login, not a failure. The jinni's own http probe must read it as up.
    def _unauthorized(_url: str, timeout: float = 3) -> NoReturn:
        raise urllib.error.HTTPError(_url, 401, "Unauthorized", Message(), None)
    monkeypatch.setattr(urllib.request, "urlopen", _unauthorized)
    info = health.probe_moonraker("", inspection.http_service_get)
    assert info.reachable is True
    assert info.failed_components == []


def test_probe_moonraker_unreachable_when_connection_refused(monkeypatch: MP) -> None:
    monkeypatch.setattr(health, "MOONRAKER_RETRIES", 2)
    monkeypatch.setattr(health.time, "sleep", lambda _s: None)
    info = health.probe_moonraker("", _probe(False, "refused"))
    assert info.reachable is False


def test_probe_moonraker_reads_failed_components_over_the_socket(monkeypatch: MP) -> None:
    # The Moonraker socket is auth-free, so a soft fail (a component that failed to load) stays seen
    # even when force_logins blocks the HTTP body. This is what the safety net attributes on.
    monkeypatch.setattr(
        health.moonraker_client, "server_info",
        lambda _path: {"klippy_state": "ready", "failed_components": ["timelapse"], "warnings": []},
    )
    info = health.probe_moonraker("/tmp/moonraker.sock", _probe(False, ""))
    assert info.reachable is True
    assert info.failed_components == ["timelapse"]


def test_parse_server_info_reads_failed_components() -> None:
    body = '{"result": {"klippy_state": "ready", "klippy_connected": true, ' \
           '"failed_components": ["notifier"], "warnings": ["[notifier phone] failed to load"]}}'
    info = health._parse_server_info(body)
    assert info.reachable is True
    assert info.failed_components == ["notifier"]
    assert info.warnings == ["[notifier phone] failed to load"]


def test_parse_server_info_tolerates_non_json() -> None:
    info = health._parse_server_info("<html>oops</html>")
    assert info.reachable is True
    assert info.failed_components == []


def test_moonraker_info_defaults() -> None:
    info = MoonrakerInfo(reachable=True, raw="")
    assert info.failed_components == []
    assert info.warnings == []


class _HealthJinni(KlipperPrinterJinni):
    def __init__(self, sockets: dict[str, str] | None = None) -> None:
        self._sockets = sockets or {}

    def device_paths(self) -> dict[str, str]:
        return {**{key: f"/dev/null/{key}" for key in KLIPPER_PATH_KEYS}, **self._sockets}


def _sockets() -> dict[str, str]:
    return {"KLIPPER_UDS": "/tmp/klippy.sock", "MOONRAKER_UDS": "/tmp/moonraker.sock"}


def test_health_assembles_a_device_report(monkeypatch: MP) -> None:
    # The shared klipper tier reports only the domain services; a device's own infrastructure (the
    # U1 broker) is the device jinni's to diagnose, so health() here carries no broker fact.
    jinni = _HealthJinni(_sockets())
    monkeypatch.setattr(health.klippy, "query_klippy_state", lambda _path: "ready")
    monkeypatch.setattr(
        health.moonraker_client, "server_info",
        lambda _path: {"klippy_state": "ready", "failed_components": ["notifier"], "warnings": []},
    )

    report = jinni.health()

    assert report.services[KLIPPER_SERVICE].ready is True
    assert report.services[MOONRAKER_SERVICE].failed_components == ("notifier",)
    assert report.diagnosis == ""
    assert report.healthy is False  # moonraker reachable but a component failed to load


def test_health_is_healthy_when_every_service_is_ready(monkeypatch: MP) -> None:
    jinni = _HealthJinni(_sockets())
    monkeypatch.setattr(health.klippy, "query_klippy_state", lambda _path: "ready")
    monkeypatch.setattr(
        health.moonraker_client, "server_info",
        lambda _path: {"klippy_state": "ready", "failed_components": [], "warnings": []},
    )

    assert jinni.health().healthy is True
