# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Single-instance, bounded jinni supervision (ADR-0037 invariants 2 and 3).

These cover the supervisor's lifecycle decisions without a real child: the pidfile round-trip,
recycling an orphan left by a dead daemon (kill-before-respawn), and giving up after bounded spawn
attempts rather than looping forever. The real-subprocess end-to-end lives in
tests/integration/test_jinni_supervisor.py.
"""
import signal
import sys
from pathlib import Path

import pytest

from core.jinni_client import supervisor, transport


@pytest.fixture
def socket_path(tmp_path: Path) -> str:
    return str(tmp_path / "jinni.sock")


@pytest.fixture
def process_table(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Stands in for /proc, so a test can say what the pidfile's number is running right now."""
    root = tmp_path / "proc"
    root.mkdir()
    monkeypatch.setattr(supervisor, "_PROC_ROOT", root)
    return root


def record_running(process_table: Path, pid: int, arguments: list[str]) -> None:
    entry = process_table / str(pid)
    entry.mkdir()
    (entry / "cmdline").write_bytes("\0".join([*arguments, ""]).encode())


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
    monkeypatch: pytest.MonkeyPatch, socket_path: str, process_table: Path,
) -> None:
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(supervisor.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    supervisor._write_pidfile(socket_path, 777)
    record_running(process_table, 777, [sys.executable, "-m", "jinni", socket_path])
    Path(socket_path).write_text("")

    supervisor._recycle_orphan(socket_path)

    assert killed == [(777, signal.SIGKILL)]
    assert supervisor._read_pidfile(socket_path) is None
    assert not Path(socket_path).exists()


def test_recycle_orphan_spares_the_process_a_reboot_gave_that_number_to(
    monkeypatch: pytest.MonkeyPatch, socket_path: str, process_table: Path,
) -> None:
    """The pidfile survives a reboot; the jinni does not. What answers to its number afterwards is a
    stranger, and the enrollment step that watches the daemon start is one of the candidates."""
    killed: list[int] = []
    monkeypatch.setattr(supervisor.os, "kill", lambda pid, sig: killed.append(pid))
    supervisor._write_pidfile(socket_path, 777)
    record_running(process_table, 777, ["sh", "-c", "sleep 5 && kill -0 $(cat daemon.pid)"])

    supervisor._recycle_orphan(socket_path)

    assert killed == []
    assert supervisor._read_pidfile(socket_path) is None


def test_recycle_orphan_spares_a_jinni_serving_a_different_socket(
    monkeypatch: pytest.MonkeyPatch, socket_path: str, process_table: Path,
) -> None:
    killed: list[int] = []
    monkeypatch.setattr(supervisor.os, "kill", lambda pid, sig: killed.append(pid))
    supervisor._write_pidfile(socket_path, 777)
    another_socket = "/somewhere/else/jinni.sock"
    record_running(process_table, 777, [sys.executable, "-m", "jinni", another_socket])

    supervisor._recycle_orphan(socket_path)

    assert killed == []


def test_recycle_orphan_spares_a_number_no_process_answers_to(
    monkeypatch: pytest.MonkeyPatch, socket_path: str, process_table: Path,
) -> None:
    killed: list[int] = []
    monkeypatch.setattr(supervisor.os, "kill", lambda pid, sig: killed.append(pid))
    supervisor._write_pidfile(socket_path, 777)

    supervisor._recycle_orphan(socket_path)

    assert killed == []
    assert supervisor._read_pidfile(socket_path) is None


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
