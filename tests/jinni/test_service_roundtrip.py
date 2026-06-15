"""The jinni-as-a-process final form (ADR-0037): the daemon talks to the jinni over a Unix socket.

These start the real service on a temp socket and drive it through the real client (`protocol.call`,
run off-loop so the blocking socket does not stall the server), proving the typed shapes round-trip,
the handshake reports versions, and an incompatible peer or unknown verb is refused. This is the
transport the production seam flips onto; the wire format is single-source in `jinni.protocol`.
"""
import asyncio
import shutil
import tempfile
from collections.abc import AsyncIterator, Iterator

import pytest

from jinni import protocol, service
from jinni.contracts import (
    KLIPPER_SERVICE,
    MOONRAKER_SERVICE,
    RESTART_KLIPPER,
    RESTART_MOONRAKER,
    CommandEffect,
    DeviceHealth,
    ServiceHealth,
)
from jinni.klipper import KLIPPER_PATH_KEYS, KlipperPrinterJinni
from jinni.printer_comms import frame


class _FakeJinni(KlipperPrinterJinni):
    def device_paths(self) -> dict[str, str]:
        return {key: f"/dev/null/{key}" for key in KLIPPER_PATH_KEYS}

    def version(self) -> str:
        return "9.9-test"

    def health(self) -> DeviceHealth:
        return DeviceHealth(
            services={
                KLIPPER_SERVICE: ServiceHealth(ready=True, detail="ready"),
                MOONRAKER_SERVICE: ServiceHealth(
                    ready=False, detail="down", failed_components=("notifier",), warnings=("w",),
                ),
            },
            diagnosis="broker note",
        )

    def classify_commands(self, commands: list[str]) -> list[CommandEffect]:
        return [CommandEffect(True, True, False, RESTART_KLIPPER) for _ in commands]

    def blocked_actions(self) -> frozenset[str]:
        return frozenset({RESTART_KLIPPER, RESTART_MOONRAKER})

    async def watch_blocked_actions(self) -> AsyncIterator[frozenset[str]]:
        yield frozenset({RESTART_KLIPPER, RESTART_MOONRAKER})
        yield frozenset()

    def restart_command(self, hook: str) -> str | None:
        return {"klipper": "/etc/init.d/S60klipper restart"}.get(hook)

    def capability_flags(self) -> set[str]:
        return {"overlay", "managed-service"}


@pytest.fixture
def socket_path() -> Iterator[str]:
    # A short dir: macOS caps an AF_UNIX path near 104 chars and pytest's tmp_path blows past it.
    directory = tempfile.mkdtemp(prefix="b3d", dir="/tmp")
    try:
        yield f"{directory}/j.sock"
    finally:
        shutil.rmtree(directory, ignore_errors=True)


async def test_typed_shapes_round_trip_over_the_socket(socket_path: str) -> None:
    server = await service.serve(socket_path, _FakeJinni())
    async with server:
        report = await asyncio.to_thread(protocol.call, socket_path, "health", [])
        effects = await asyncio.to_thread(protocol.call, socket_path, "classify_commands", [["x"]])
        blocked = await asyncio.to_thread(protocol.call, socket_path, "blocked_actions", [])

    assert isinstance(report, DeviceHealth)
    assert report.services[MOONRAKER_SERVICE].failed_components == ("notifier",)
    assert report.diagnosis == "broker note"
    assert report.healthy is False
    assert effects == [CommandEffect(True, True, False, RESTART_KLIPPER)]
    assert blocked == frozenset({RESTART_KLIPPER, RESTART_MOONRAKER})


async def test_primitive_verbs_round_trip(socket_path: str) -> None:
    server = await service.serve(socket_path, _FakeJinni())

    async def call(verb: str, args: list) -> object:
        return await asyncio.to_thread(protocol.call, socket_path, verb, args)

    async with server:
        assert await call("restart_command", ["klipper"]) == "/etc/init.d/S60klipper restart"
        assert await call("restart_command", ["nope"]) is None
        assert await call("capability_flags", []) == {"overlay", "managed-service"}


async def test_blocked_actions_stream_pushes_each_change_over_the_socket(socket_path: str) -> None:
    server = await service.serve(socket_path, _FakeJinni())
    async with server:
        frames = [
            frozenset(tokens)
            async for tokens in protocol.stream(socket_path, protocol.SUBSCRIBE_BLOCKED_ACTIONS)
        ]
    assert frames == [frozenset({RESTART_KLIPPER, RESTART_MOONRAKER}), frozenset()]


async def test_handshake_reports_protocol_and_jinni_versions(socket_path: str) -> None:
    server = await service.serve(socket_path, _FakeJinni())
    async with server:
        hello = await asyncio.to_thread(protocol.call, socket_path, protocol.HELLO, [])
    assert hello == {"protocol_version": protocol.PROTOCOL_VERSION, "jinni_version": "9.9-test"}


def test_an_incompatible_protocol_version_is_refused() -> None:
    bad = frame.encode({"v": protocol.PROTOCOL_VERSION + 999, "verb": protocol.HELLO, "args": []})
    reply = service.serve_request(_FakeJinni(), bad)
    with pytest.raises(protocol.ProtocolError, match="update the adapter"):
        protocol.parse_result(protocol.HELLO, reply)


def test_an_unknown_verb_is_refused() -> None:
    bad = frame.encode({"v": protocol.PROTOCOL_VERSION, "verb": "rm_rf", "args": []})
    reply = service.serve_request(_FakeJinni(), bad)
    with pytest.raises(protocol.ProtocolError, match="unknown verb"):
        protocol.parse_result("rm_rf", reply)
