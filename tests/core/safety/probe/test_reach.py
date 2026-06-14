"""The low-level reachability primitives shared by the per-service probes."""
import socket
import urllib.error
import urllib.request
from email.message import Message
from typing import NoReturn

import pytest

from core.safety.probe import reach


def test_service_get_reads_auth_required_as_up(monkeypatch: pytest.MonkeyPatch) -> None:
    # force_logins answers 401: the service IS up, it just demands a login. service_get must report
    # up so the safety net does not deactivate the plugin that turned auth on.
    def _unauthorized(_url: str, timeout: float = 3) -> NoReturn:
        raise urllib.error.HTTPError(_url, 401, "Unauthorized", Message(), None)
    monkeypatch.setattr(urllib.request, "urlopen", _unauthorized)
    up, body = reach.service_get("http://localhost:7125/server/info")
    assert up is True
    assert "up" in body


def test_service_get_reports_a_refused_connection_as_down(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refused(_url: str, timeout: float = 3) -> NoReturn:
        raise ConnectionRefusedError("refused")
    monkeypatch.setattr(urllib.request, "urlopen", _refused)
    up, _body = reach.service_get("http://localhost:7125/server/info")
    assert up is False


def test_port_listening_detects_a_bound_then_closed_port() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        bound_port = listener.getsockname()[1]
        assert reach.port_listening(bound_port) is True
    assert reach.port_listening(bound_port) is False
