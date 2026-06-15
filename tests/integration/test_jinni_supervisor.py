"""The daemon supervising a real jinni child over the socket (ADR-0037 THE FLIP).

The daemon spawns `python -m jinni <socket>`, waits for the protocol handshake, and routes the seam
over the socket. These stand the real child up end to end on a short /tmp socket and exercise the
lifecycle: it answers a verb, its pidfile tracks the live child, a second start recycles the first
(single-instance), and stop clears the runtime files. Bounded so a stuck child fails fast, never
hangs the gate. No adapter is on the path here, so the child loads the generic jinni.
"""
import shutil
import tempfile
import time
from collections.abc import Iterator

import pytest

from core import jinni_client
from core.jinni_client import supervisor, transport
from jinni import protocol
from jinni.contracts import DeviceHealth


@pytest.fixture
def socket_path() -> Iterator[str]:
    directory = tempfile.mkdtemp(prefix="b3d", dir="/tmp")
    try:
        yield f"{directory}/j.sock"
    finally:
        shutil.rmtree(directory, ignore_errors=True)


@pytest.fixture(autouse=True)
def reset_transport() -> Iterator[None]:
    yield
    jinni_client.use_in_process()


def _await_exit(process: object) -> None:
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and process.poll() is None:  # type: ignore[attr-defined]
        time.sleep(0.05)


@pytest.mark.timeout(30)
def test_daemon_spawns_the_jinni_and_talks_over_the_socket(socket_path: str) -> None:
    process = supervisor.start_jinni(socket_path)
    try:
        assert transport.socket_path() == socket_path
        hello = protocol.call(socket_path, protocol.HELLO, [])
        assert hello["protocol_version"] == protocol.PROTOCOL_VERSION
        report = jinni_client.health()
        assert isinstance(report, DeviceHealth)
        assert report.healthy is True
    finally:
        supervisor.stop_jinni(process)
    assert transport.socket_path() is None


@pytest.mark.timeout(30)
def test_the_pidfile_tracks_the_live_child_and_stop_clears_it(socket_path: str) -> None:
    process = supervisor.start_jinni(socket_path)
    try:
        assert supervisor._read_pidfile(socket_path) == process.pid
    finally:
        supervisor.stop_jinni(process)
    assert supervisor._read_pidfile(socket_path) is None


@pytest.mark.timeout(30)
def test_a_second_start_recycles_the_first(socket_path: str) -> None:
    first = supervisor.start_jinni(socket_path)
    second = supervisor.start_jinni(socket_path)
    try:
        _await_exit(first)
        assert first.poll() is not None
        assert supervisor._read_pidfile(socket_path) == second.pid
        assert jinni_client.health().healthy is True
    finally:
        supervisor.stop_jinni(second)
        if first.poll() is None:
            supervisor.stop_jinni(first)
