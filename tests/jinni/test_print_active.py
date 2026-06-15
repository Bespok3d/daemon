"""The klipper printer jinni reads live print state and names what a print blocks (ADR-0037).

`print_active()` reads Klipper's print_stats over its auth-free API socket first (so it survives the
moonraker-auth plugin's force_logins), falling back to Moonraker HTTP. `blocked_actions()` is the
live blocked-action TOKEN set the daemon's print guard checks: while a print runs, restarting
Klipper, Moonraker, or the display is forbidden. The base jinni blocks nothing (no print to guard).
"""
import json
import urllib.error
import urllib.request
from email.message import Message
from typing import NoReturn

import pytest

from jinni.base import Jinni
from jinni.contracts import RESTART_KLIPPER, RESTART_MOONRAKER
from jinni.klipper import KLIPPER_PATH_KEYS, KlipperPrinterJinni
from jinni.printer_comms import klippy

MP = pytest.MonkeyPatch


class _PrinterJinni(KlipperPrinterJinni):
    def __init__(self, sockets: dict[str, str] | None = None) -> None:
        self._sockets = sockets or {}

    def device_paths(self) -> dict[str, str]:
        return {**{key: f"/dev/null/{key}" for key in KLIPPER_PATH_KEYS}, **self._sockets}


class _GenericJinni(Jinni):
    def device_paths(self) -> dict[str, str]:
        return {"BESPOK3D_PLUGINS": "/no/such/plugins"}


class _Response:
    def __init__(self, body: str) -> None:
        self._body = body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body.encode()


def _print_stats(state: str) -> str:
    return json.dumps({"result": {"status": {"print_stats": {"state": state}}}})


def test_print_active_reads_the_klipper_api_socket(monkeypatch: MP) -> None:
    monkeypatch.setattr(klippy, "query_print_state", lambda _path: "printing")
    assert _PrinterJinni({"KLIPPER_UDS": "/tmp/k.sock"}).print_active() == (True, "printing")


def test_print_active_survives_moonraker_force_logins(monkeypatch: MP) -> None:
    # Klipper's socket reports the print even when Moonraker's HTTP API answers 401 under
    # force_logins: the auth-immune socket is the source, the 401 fallback is never consulted.
    def _unauthorized(_url: str, timeout: float = 3) -> NoReturn:
        raise urllib.error.HTTPError(_url, 401, "Unauthorized", Message(), None)
    monkeypatch.setattr(urllib.request, "urlopen", _unauthorized)
    monkeypatch.setattr(klippy, "query_print_state", lambda _path: "printing")
    assert _PrinterJinni({"KLIPPER_UDS": "/tmp/k.sock"}).print_active() == (True, "printing")


def test_print_active_falls_back_to_moonraker_without_a_socket(monkeypatch: MP) -> None:
    paused = _Response(_print_stats("paused"))
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: paused)
    assert _PrinterJinni().print_active() == (True, "paused")


def test_print_active_idle_when_socket_unreachable_and_moonraker_silent(monkeypatch: MP) -> None:
    def _down(_url: str, timeout: float = 3) -> NoReturn:
        raise OSError("down")
    monkeypatch.setattr(klippy, "query_print_state", lambda _path: None)
    monkeypatch.setattr(urllib.request, "urlopen", _down)
    assert _PrinterJinni({"KLIPPER_UDS": "/tmp/k.sock"}).print_active() == (False, "")


def test_is_active_print_state_classifies_printing_and_paused() -> None:
    jinni = _PrinterJinni()
    assert jinni.is_active_print_state("printing") is True
    assert jinni.is_active_print_state("paused") is True
    assert jinni.is_active_print_state("standby") is False


def test_blocked_actions_while_printing(monkeypatch: MP) -> None:
    monkeypatch.setattr(klippy, "query_print_state", lambda _path: "printing")
    blocked = _PrinterJinni({"KLIPPER_UDS": "/tmp/k.sock"}).blocked_actions()
    assert blocked == frozenset({RESTART_KLIPPER, RESTART_MOONRAKER})


def test_blocked_actions_empty_when_idle(monkeypatch: MP) -> None:
    monkeypatch.setattr(klippy, "query_print_state", lambda _path: "standby")
    assert _PrinterJinni({"KLIPPER_UDS": "/tmp/k.sock"}).blocked_actions() == frozenset()


def test_blocked_actions_include_the_display_when_the_device_has_one(monkeypatch: MP) -> None:
    from jinni.contracts import RESTART_DISPLAY

    class _DisplayJinni(_PrinterJinni):
        def display_service_tokens(self) -> tuple[str, ...]:
            return ("lmdctl",)

    monkeypatch.setattr(klippy, "query_print_state", lambda _path: "paused")
    blocked = _DisplayJinni({"KLIPPER_UDS": "/tmp/k.sock"}).blocked_actions()
    assert blocked == frozenset({RESTART_KLIPPER, RESTART_MOONRAKER, RESTART_DISPLAY})


def test_base_jinni_blocks_nothing_and_never_prints() -> None:
    generic = _GenericJinni()
    assert generic.print_active() == (False, "")
    assert generic.is_active_print_state("printing") is False
    assert generic.blocked_actions() == frozenset()
