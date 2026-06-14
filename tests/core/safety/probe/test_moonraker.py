"""Moonraker health-probe tests, incl. the original force_logins-401 regression."""
import json
import urllib.error
import urllib.request
from email.message import Message
from typing import NoReturn

import pytest

from core.safety.probe import moonraker


def test_probe_moonraker_reads_force_logins_401_as_up(monkeypatch: pytest.MonkeyPatch) -> None:
    # The bug that started the safety net: moonraker-auth turns on force_logins, so /server/info
    # answers 401. That is the server up and demanding a login, not a failure: probing it must NOT
    # report it down (which auto-deactivated the very plugin that enabled auth).
    def _unauthorized(_url: str, timeout: float = 3) -> NoReturn:
        raise urllib.error.HTTPError(_url, 401, "Unauthorized", Message(), None)
    monkeypatch.setattr(urllib.request, "urlopen", _unauthorized)
    info = moonraker.probe_moonraker()
    assert info.reachable is True
    assert info.failed_components == []


def test_probe_moonraker_unreachable_when_connection_refused(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    def _refused(_url: str, timeout: float = 3) -> NoReturn:
        raise ConnectionRefusedError("refused")
    monkeypatch.setattr(urllib.request, "urlopen", _refused)
    monkeypatch.setattr(moonraker, "MOONRAKER_RETRIES", 2)
    monkeypatch.setattr(moonraker.time, "sleep", lambda _s: None)
    info = moonraker.probe_moonraker()
    assert info.reachable is False


def test_probe_moonraker_once_reads_failed_components_over_the_socket(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    # The Moonraker socket is auth-free, so soft fails (a component that failed to load) stay seen
    # even when force_logins blocks the HTTP body. This is what the safety net needs to attribute.
    monkeypatch.setattr(
        moonraker.moonraker_client, "server_info",
        lambda _path: {"klippy_state": "ready", "failed_components": ["timelapse"], "warnings": []},
    )
    info = moonraker._probe_moonraker_once("/tmp/moonraker.sock")
    assert info.reachable is True
    assert info.failed_components == ["timelapse"]


def test_probe_moonraker_once_falls_back_to_http_when_socket_unreachable(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(moonraker.moonraker_client, "server_info", lambda _path: None)
    monkeypatch.setattr(moonraker, "service_get", lambda _url, timeout=3: (True, "up via http"))
    info = moonraker._probe_moonraker_once("/tmp/moonraker.sock")
    assert info.reachable is True


def test_parse_server_info_reads_failed_components() -> None:
    body = json.dumps({"result": {
        "klippy_state": "ready", "klippy_connected": True,
        "failed_components": ["notifier"], "warnings": ["[notifier phone] failed to load"],
    }})
    info = moonraker._parse_server_info(body)
    assert info.reachable is True
    assert info.klippy_state == "ready"
    assert info.klippy_connected is True
    assert info.failed_components == ["notifier"]
    assert info.warnings == ["[notifier phone] failed to load"]


def test_parse_server_info_tolerates_non_json() -> None:
    info = moonraker._parse_server_info("<html>oops</html>")
    assert info.reachable is True
    assert info.failed_components == []
    assert info.warnings == []
