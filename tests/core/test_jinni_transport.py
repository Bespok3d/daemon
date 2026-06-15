"""The jinni seam over the socket (ADR-0037 THE FLIP).

The seam's transport is pluggable: in-process by default, the socket once the daemon spawns its
jinni child. These stand the real jinni service up on a temp socket, flip the seam onto it, and
prove every verb routes over the wire (typed shapes round-trip; capabilities_report folds
interface_extras in the service's process). The transport resets to in-process after each test so
the rest of the core suite keeps its in-process default.
"""
import asyncio
import shutil
import tempfile
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest

from core import jinni_client
from core.jinni_client import transport
from jinni import service
from jinni.contracts import (
    KLIPPER_SERVICE,
    RESTART_KLIPPER,
    CommandEffect,
    DeviceHealth,
    ServiceHealth,
)
from jinni.health import HEALTH_PROBE_BUDGET_S
from jinni.klipper import KLIPPER_PATH_KEYS, KlipperPrinterJinni
from jinni.printer_comms import frame


class _FakeJinni(KlipperPrinterJinni):
    def device_paths(self) -> dict[str, str]:
        return {key: f"/dev/null/{key}" for key in KLIPPER_PATH_KEYS}

    def health(self) -> DeviceHealth:
        return DeviceHealth(
            services={KLIPPER_SERVICE: ServiceHealth(ready=True, detail="up")},
            diagnosis="broker note",
        )

    def classify_commands(self, commands: list[str]) -> list[CommandEffect]:
        return [CommandEffect(True, True, False, RESTART_KLIPPER) for _ in commands]

    def blocked_actions(self) -> frozenset[str]:
        return frozenset({RESTART_KLIPPER})

    async def watch_blocked_actions(self) -> AsyncIterator[frozenset[str]]:
        yield frozenset({RESTART_KLIPPER})
        yield frozenset()

    def capabilities(self) -> dict:
        return {"adapter": "fake"}


@pytest.fixture
def socket_path() -> Iterator[str]:
    # A short dir: macOS caps an AF_UNIX path near 104 chars and pytest's tmp_path blows past it.
    directory = tempfile.mkdtemp(prefix="b3d", dir="/tmp")
    try:
        yield f"{directory}/j.sock"
    finally:
        shutil.rmtree(directory, ignore_errors=True)


@pytest.fixture(autouse=True)
def reset_transport() -> Iterator[None]:
    yield
    jinni_client.use_in_process()


def test_in_process_is_the_default() -> None:
    assert transport.socket_path() is None


async def test_verbs_route_over_the_socket(socket_path: str) -> None:
    server = await service.serve(socket_path, _FakeJinni())
    jinni_client.use_socket(socket_path)
    async with server:
        report = await asyncio.to_thread(jinni_client.health)
        effects = await asyncio.to_thread(jinni_client.classify_commands, ["restart-klipper"])
        blocked = await asyncio.to_thread(jinni_client.blocked_actions)
    assert isinstance(report, DeviceHealth)
    assert report.services[KLIPPER_SERVICE].ready
    assert report.diagnosis == "broker note"
    assert effects == [CommandEffect(True, True, False, RESTART_KLIPPER)]
    assert blocked == frozenset({RESTART_KLIPPER})


def test_health_call_timeout_exceeds_its_probe_budget(
    socket_path: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression: health() retries while a just-restarted service comes back (e.g. installing a
    # plugin that bounces Moonraker), far longer than the default reply timeout. Its socket call
    # needs a timeout above that retry budget, or the slow restart reads as "no reply from the
    # jinni for 'health'". Capture the timeout the seam hands the socket call.
    captured: dict[str, float] = {}

    def fake_call(path: str, verb: str, args: list[Any], timeout: float = frame.DEFAULT_TIMEOUT_S) -> DeviceHealth:  # noqa: E501
        captured[verb] = timeout
        return DeviceHealth(services={KLIPPER_SERVICE: ServiceHealth(ready=True, detail="up")})

    monkeypatch.setattr(jinni_client.protocol, "call", fake_call)
    jinni_client.use_socket(socket_path)
    jinni_client.health()
    assert captured["health"] > frame.DEFAULT_TIMEOUT_S
    assert captured["health"] >= HEALTH_PROBE_BUDGET_S


async def test_blocked_actions_stream_routes_over_the_socket(socket_path: str) -> None:
    server = await service.serve(socket_path, _FakeJinni())
    jinni_client.use_socket(socket_path)
    async with server:
        frames = [blocked async for blocked in jinni_client.subscribe_blocked_actions()]
    assert frames == [frozenset({RESTART_KLIPPER}), frozenset()]


async def test_capabilities_report_folds_extras_over_the_socket(socket_path: str) -> None:
    server = await service.serve(socket_path, _FakeJinni())
    jinni_client.use_socket(socket_path)
    async with server:
        report = await asyncio.to_thread(jinni_client.capabilities_report)
    assert report["adapter"] == "fake"
    assert "interface_extras" in report
