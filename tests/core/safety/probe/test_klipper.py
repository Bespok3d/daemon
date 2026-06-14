"""Klipper health-probe tests (the 401-as-up handling lives in test_reach)."""
import pytest

from core.safety.probe import klipper


def test_klipper_ready_once_prefers_the_api_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    # Klipper's API socket is auth-free, so it is the source of truth even when Moonraker forces
    # logins; the HTTP probe is only the fallback when the socket is unavailable.
    monkeypatch.setattr(klipper.klippy, "query_klippy_state", lambda _path: "ready")
    healthy, out = klipper._klipper_ready_once("/tmp/klippy.sock")
    assert healthy is True
    assert "api socket" in out


def test_klipper_ready_once_falls_back_to_http_without_a_socket(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(klipper, "service_get", lambda _url, timeout=3: (True, "via http"))
    healthy, out = klipper._klipper_ready_once("")
    assert healthy is True
    assert out == "via http"
