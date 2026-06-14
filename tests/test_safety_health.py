"""Health-probe + self-heal tests for the safety net.

These exercise behaviour through injected seams (a fake probe / prune / restart) and pure parsing,
never by monkeypatching our own functions.
"""
import json
import urllib.error
import urllib.request
from pathlib import Path

from core.safety import health


def _raise_http(code: int):
    def _fake(_url, timeout=3):  # noqa: ANN001, ANN202 - test seam matching urlopen
        raise urllib.error.HTTPError(_url, code, "Unauthorized", {}, None)  # type: ignore[arg-type]
    return _fake


def test_probe_moonraker_reads_force_logins_401_as_up(monkeypatch) -> None:
    # moonraker-auth turns on force_logins, so /server/info answers 401. That is the server up and
    # demanding a login, not a failure: probing it must NOT report it down (which made the safety
    # net auto-deactivate the very plugin that enabled auth).
    monkeypatch.setattr(urllib.request, "urlopen", _raise_http(401))
    info = health.probe_moonraker()
    assert info.reachable is True
    assert info.failed_components == []


def test_klipper_healthy_reads_force_logins_401_as_up(monkeypatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", _raise_http(401))
    healthy, _out = health.klipper_healthy()
    assert healthy is True


def test_probe_moonraker_unreachable_when_connection_refused(monkeypatch) -> None:
    def _refused(_url, timeout=3):  # noqa: ANN001, ANN202
        raise ConnectionRefusedError("refused")
    monkeypatch.setattr(urllib.request, "urlopen", _refused)
    monkeypatch.setattr(health, "MOONRAKER_RETRIES", 2)
    monkeypatch.setattr(health.time, "sleep", lambda _s: None)
    info = health.probe_moonraker()
    assert info.reachable is False


def test_klipper_ready_once_prefers_the_api_socket(monkeypatch) -> None:
    # Klipper's API socket is auth-free, so it is the source of truth even when Moonraker forces
    # logins; the HTTP probe is only the fallback when the socket is unavailable.
    monkeypatch.setattr(health.klippy_uds, "query_klippy_state", lambda _path: "ready")
    healthy, out = health._klipper_ready_once("/tmp/klippy.sock")
    assert healthy is True
    assert "api socket" in out


def test_klipper_ready_once_falls_back_to_http_without_a_socket(monkeypatch) -> None:
    monkeypatch.setattr(health, "_service_get", lambda _url, timeout=3: (True, "via http"))
    healthy, out = health._klipper_ready_once("")
    assert healthy is True
    assert out == "via http"


def test_probe_moonraker_once_reads_failed_components_over_the_socket(monkeypatch) -> None:
    # The Moonraker socket is auth-free, so soft fails (a component that failed to load) stay seen
    # even when force_logins blocks the HTTP body. This is what the safety net needs to attribute.
    monkeypatch.setattr(
        health.moonraker_uds, "server_info",
        lambda _path: {"klippy_state": "ready", "failed_components": ["timelapse"], "warnings": []},
    )
    info = health._probe_moonraker_once("/tmp/moonraker.sock")
    assert info.reachable is True
    assert info.failed_components == ["timelapse"]


def test_probe_moonraker_once_falls_back_to_http_when_socket_unreachable(monkeypatch) -> None:
    monkeypatch.setattr(health.moonraker_uds, "server_info", lambda _path: None)
    monkeypatch.setattr(health, "_service_get", lambda _url, timeout=3: (True, "auth required 401"))
    info = health._probe_moonraker_once("/tmp/moonraker.sock")
    assert info.reachable is True


def test_parse_server_info_reads_failed_components() -> None:
    body = json.dumps({"result": {
        "klippy_state": "ready", "klippy_connected": True,
        "failed_components": ["notifier"], "warnings": ["[notifier phone] failed to load"],
    }})
    info = health.parse_server_info(body)
    assert info.reachable is True
    assert info.klippy_state == "ready"
    assert info.klippy_connected is True
    assert info.failed_components == ["notifier"]
    assert info.warnings == ["[notifier phone] failed to load"]


def test_parse_server_info_tolerates_non_json() -> None:
    info = health.parse_server_info("<html>oops</html>")
    assert info.reachable is True
    assert info.failed_components == []
    assert info.warnings == []


def test_prune_dead_config_links_removes_only_broken_links(tmp_path: Path) -> None:
    config_dir = tmp_path / "moonraker"
    config_dir.mkdir()
    real_target = tmp_path / "real.cfg"
    real_target.write_text("[spoolman]\n")
    live_link = config_dir / "live.cfg"
    live_link.symlink_to(real_target)
    dead_link = config_dir / "gone.cfg"
    dead_link.symlink_to(tmp_path / "missing.cfg")

    removed = health.prune_dead_config_links([config_dir])

    assert removed == [str(dead_link)]
    assert not dead_link.is_symlink()
    assert live_link.is_symlink()
