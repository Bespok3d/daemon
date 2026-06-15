"""The base Jinni owns reachability: is a localhost service answering, is a TCP port open.

These were the low-level primitives the safety net's per-service probes built on; the jinni is the
device's half, so reaching the printer's services is its concern (ADR-0029 Part 2, P7). The
force_logins-401 handling is the regression that started the safety net: an auth-required answer
means the service is UP, not down.
"""
import socket
import urllib.error
import urllib.request
from email.message import Message
from typing import NoReturn

import pytest

import jinni


class _ReachableJinni(jinni.Jinni):
    def device_paths(self) -> dict[str, str]:
        return {"BESPOK3D_PLUGINS": "/no/such/plugins"}


def test_service_get_reads_auth_required_as_up(monkeypatch: pytest.MonkeyPatch) -> None:
    def _unauthorized(_url: str, timeout: float = 3) -> NoReturn:
        raise urllib.error.HTTPError(_url, 401, "Unauthorized", Message(), None)
    monkeypatch.setattr(urllib.request, "urlopen", _unauthorized)
    up, body = _ReachableJinni().service_get("http://localhost:7125/server/info")
    assert up is True
    assert "up" in body


def test_service_get_reports_a_refused_connection_as_down(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refused(_url: str, timeout: float = 3) -> NoReturn:
        raise ConnectionRefusedError("refused")
    monkeypatch.setattr(urllib.request, "urlopen", _refused)
    up, _body = _ReachableJinni().service_get("http://localhost:7125/server/info")
    assert up is False


def test_port_listening_detects_a_bound_then_closed_port() -> None:
    probe = _ReachableJinni()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        bound_port = listener.getsockname()[1]
        assert probe.port_listening(bound_port) is True
    assert probe.port_listening(bound_port) is False
