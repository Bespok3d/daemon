"""Single-instance, bounded jinni supervision (ADR-0037 invariants 2 and 3).

These cover the supervisor's lifecycle decisions without a real child: the pidfile round-trip,
recycling an orphan left by a dead daemon (kill-before-respawn), and giving up after bounded spawn
attempts rather than looping forever. The real-subprocess end-to-end lives in
tests/integration/test_jinni_supervisor.py.
"""
import signal
from pathlib import Path

import pytest

from core.jinni_client import supervisor, transport


@pytest.fixture
def socket_path(tmp_path: Path) -> str:
    return str(tmp_path / "jinni.sock")


@pytest.fixture(autouse=True)
def reset_transport() -> None:
    transport.use_in_process()


def test_pidfile_round_trips(socket_path: str) -> None:
    supervisor._write_pidfile(socket_path, 4242)
    assert supervisor._read_pidfile(socket_path) == 4242
    supervisor._clear_runtime_files(socket_path)
    assert supervisor._read_pidfile(socket_path) is None


def test_a_missing_or_garbage_pidfile_reads_as_none(socket_path: str) -> None:
    assert supervisor._read_pidfile(socket_path) is None
    Path(socket_path).with_name("jinni.pid").write_text("not-a-pid")
    assert supervisor._read_pidfile(socket_path) is None


def test_recycle_orphan_kills_the_recorded_pid_and_clears_the_files(
    monkeypatch: pytest.MonkeyPatch, socket_path: str,
) -> None:
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(supervisor.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    supervisor._write_pidfile(socket_path, 777)
    Path(socket_path).write_text("")

    supervisor._recycle_orphan(socket_path)

    assert killed == [(777, signal.SIGKILL)]
    assert supervisor._read_pidfile(socket_path) is None
    assert not Path(socket_path).exists()


def test_recycle_orphan_is_a_noop_without_a_pidfile(
    monkeypatch: pytest.MonkeyPatch, socket_path: str,
) -> None:
    killed: list[int] = []
    monkeypatch.setattr(supervisor.os, "kill", lambda pid, sig: killed.append(pid))
    supervisor._recycle_orphan(socket_path)
    assert killed == []


class _FakePopen:
    pid = 4242

    def kill(self) -> None:
        pass

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def poll(self) -> int:
        return 0


def test_spawn_gives_up_after_bounded_attempts(
    monkeypatch: pytest.MonkeyPatch, socket_path: str,
) -> None:
    attempts = {"count": 0}

    def fake_popen(*args: object, **kwargs: object) -> _FakePopen:
        attempts["count"] += 1
        return _FakePopen()

    monkeypatch.setattr(supervisor.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(supervisor, "_await_serving", lambda process, path: False)
    monkeypatch.setattr(supervisor.time, "sleep", lambda seconds: None)

    with pytest.raises(TimeoutError, match="did not serve"):
        supervisor.start_jinni(socket_path)

    assert attempts["count"] == supervisor._SPAWN_ATTEMPTS
    assert transport.socket_path() is None
