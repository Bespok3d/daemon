# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stopping the jinni, and waiting for one that never serves (ADR-0037 invariants 2 and 3).

The recycle-an-orphan and give-up-after-N-attempts halves live in test_jinni_supervisor.py. This
file covers what happens when the child misbehaves on the way up or on the way down: the daemon must
come back to a known state either way, because a daemon that hangs on shutdown or leaves a jinni
behind is a printer its owner cannot restart.

Every process here is fake: no jinni is spawned, no signal reaches a real pid.
"""
import subprocess
from pathlib import Path
from typing import cast

import pytest

from core.jinni_client import supervisor, transport


@pytest.fixture
def socket_path(tmp_path: Path) -> str:
    return str(tmp_path / "jinni.sock")


@pytest.fixture(autouse=True)
def reset_transport() -> None:
    transport.use_in_process()


class _ChildThatStops:
    """A jinni that shuts down when asked."""

    pid = 4242

    def __init__(self) -> None:
        self.signalled: list[str] = []

    def terminate(self) -> None:
        self.signalled.append("terminate")

    def kill(self) -> None:
        self.signalled.append("kill")

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def poll(self) -> int | None:
        return None


class _ChildThatIgnoresTerminate(_ChildThatStops):
    """A jinni wedged in an uninterruptible call: the polite signal does not reach it."""

    def wait(self, timeout: float | None = None) -> int:
        raise subprocess.TimeoutExpired(cmd="jinni", timeout=timeout or 0)


def _started_jinni(monkeypatch: pytest.MonkeyPatch, socket_path: str,
                   child: _ChildThatStops) -> _ChildThatStops:
    monkeypatch.setattr(supervisor.subprocess, "Popen", lambda *sent, **named: child)
    monkeypatch.setattr(supervisor, "_await_serving", lambda process, path: True)
    started: object = supervisor.start_jinni(socket_path)
    assert started is child
    return child


def _stop(child: _ChildThatStops) -> None:
    """stop_jinni takes the real child process; the stand-in plays one at this seam only."""
    supervisor.stop_jinni(cast("subprocess.Popen[bytes]", child))


def test_a_jinni_that_shuts_down_is_asked_politely_and_never_killed(
    monkeypatch: pytest.MonkeyPatch, socket_path: str,
) -> None:
    child = _started_jinni(monkeypatch, socket_path, _ChildThatStops())

    _stop(child)

    assert child.signalled == ["terminate"]


def test_a_wedged_jinni_is_killed_so_shutdown_never_hangs(
    monkeypatch: pytest.MonkeyPatch, socket_path: str,
) -> None:
    """Without the kill, stopping the daemon waits forever on a child that cannot answer, and the
    printer's owner is left with a service that will not restart."""
    child = _started_jinni(monkeypatch, socket_path, _ChildThatIgnoresTerminate())

    _stop(child)

    assert child.signalled == ["terminate", "kill"]


def test_stopping_clears_the_pidfile_and_the_socket(
    monkeypatch: pytest.MonkeyPatch, socket_path: str,
) -> None:
    """A pidfile left behind names a pid the next boot may have given to something else, and the
    recycle step would then signal a stranger's process."""
    child = _started_jinni(monkeypatch, socket_path, _ChildThatStops())
    Path(socket_path).write_text("")
    assert supervisor._read_pidfile(socket_path) == child.pid

    _stop(child)

    assert supervisor._read_pidfile(socket_path) is None
    assert not Path(socket_path).exists()


def test_stopping_routes_the_seam_back_in_process(
    monkeypatch: pytest.MonkeyPatch, socket_path: str,
) -> None:
    """The daemon keeps answering after its jinni is gone, in-process, rather than calling a socket
    nothing is listening on."""
    child = _started_jinni(monkeypatch, socket_path, _ChildThatStops())
    assert transport.socket_path() == socket_path

    _stop(child)

    assert transport.socket_path() is None


def test_a_child_that_dies_before_serving_is_not_waited_on_for_the_full_timeout(
    monkeypatch: pytest.MonkeyPatch, socket_path: str,
) -> None:
    """A jinni that exits at once (a missing module, a bad interpreter) must be noticed by its exit
    code, not by burning the whole handshake timeout on a process that is already gone."""
    class _ChildThatDied(_ChildThatStops):
        def poll(self) -> int | None:
            return 1

    polls = {"handshakes": 0}

    def count_handshake(path: str) -> bool:
        polls["handshakes"] += 1
        return False

    monkeypatch.setattr(supervisor, "_handshake_ok", count_handshake)

    assert supervisor._await_serving(_ChildThatDied(), socket_path) is False  # type: ignore[arg-type]
    assert polls["handshakes"] == 0


def test_a_serving_child_is_reported_up_without_waiting(
    monkeypatch: pytest.MonkeyPatch, socket_path: str,
) -> None:
    monkeypatch.setattr(supervisor, "_handshake_ok", lambda path: True)

    assert supervisor._await_serving(_ChildThatStops(), socket_path) is True  # type: ignore[arg-type]
