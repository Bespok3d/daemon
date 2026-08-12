# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Spawn and supervise the jinni child process (ADR-0037 THE FLIP).

The init system launches the daemon; the daemon launches and parents the jinni as a child process
(`python -m jinni <socket>`), polls the protocol handshake until it serves, then flips the seam
transport onto the socket. Reviving the jinni is re-exec'ing a daemonic-realm file, never a device
action. The lifecycle is single-instance and bounded (ADR-0037 invariants 2 and 3): a jinni left by
a dead daemon is recycled before a fresh one starts (kill-before-respawn, never two), a child that
fails to serve is retried with bounded backoff (never a tight loop), and stopping the daemon stops
its child and clears its pidfile.
"""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import protocol

from . import transport

_DAEMON_ROOT = Path(__file__).resolve().parents[2]
_PROC_ROOT = Path("/proc")
_HANDSHAKE_TIMEOUT_S = 10.0
_HANDSHAKE_POLL_S = 0.1
_STOP_TIMEOUT_S = 5.0
_SPAWN_ATTEMPTS = 3
_SPAWN_BACKOFF_S = 0.5


def default_socket_path() -> str:
    root = os.environ.get("BESPOK3D_DATA_ROOT", "/userdata/bespok3d")
    return f"{root}/run/jinni.sock"


def start_jinni(socket_path: str | None = None) -> subprocess.Popen[bytes]:
    """Recycle any orphaned jinni, spawn a fresh parented child on `socket_path`, wait for its
    handshake, then route the seam over the socket. Returns the child the daemon later stops.
    Blocking (the handshake poll), so the lifespan runs it off the event loop."""
    path = socket_path or default_socket_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    _recycle_orphan(path)
    process = _spawn_serving(path)
    _write_pidfile(path, process.pid)
    transport.use_socket(path)
    return process


def stop_jinni(process: subprocess.Popen[bytes]) -> None:
    """Stop the parented jinni, clear its pidfile and socket, and route the seam back in-process. A
    child that ignores the term signal is killed so shutdown never blocks."""
    path = transport.socket_path()
    transport.use_in_process()
    process.terminate()
    try:
        process.wait(timeout=_STOP_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        process.kill()
    if path is not None:
        _clear_runtime_files(path)


def _spawn_serving(socket_path: str) -> subprocess.Popen[bytes]:
    command = [sys.executable, "-m", "jinni", socket_path]
    for attempt in range(_SPAWN_ATTEMPTS):
        process = subprocess.Popen(command, cwd=str(_DAEMON_ROOT))
        if _await_serving(process, socket_path):
            return process
        _kill_child(process)
        if attempt + 1 < _SPAWN_ATTEMPTS:
            time.sleep(_SPAWN_BACKOFF_S * (attempt + 1))
    raise TimeoutError(f"the jinni did not serve on {socket_path} after {_SPAWN_ATTEMPTS} attempts")


def _await_serving(process: subprocess.Popen[bytes], socket_path: str) -> bool:
    deadline = time.monotonic() + _HANDSHAKE_TIMEOUT_S
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        if _handshake_ok(socket_path):
            return True
        time.sleep(_HANDSHAKE_POLL_S)
    return False


def _handshake_ok(socket_path: str) -> bool:
    try:
        protocol.call(socket_path, protocol.HELLO, [])
        return True
    except protocol.ProtocolError:
        return False


def _recycle_orphan(socket_path: str) -> None:
    pid = _read_pidfile(socket_path)
    if pid is not None and _pid_is_our_jinni(pid, socket_path):
        _kill_pid(pid)
    _clear_runtime_files(socket_path)


def _pid_is_our_jinni(pid: int, socket_path: str) -> bool:
    """The pidfile lives on storage that outlives a reboot, and after one its number belongs to
    whatever the kernel handed it to next, so a recorded number on its own proves nothing. Kill it
    only while its command line is still the jinni serving this socket."""
    try:
        command_line = (_PROC_ROOT / str(pid) / "cmdline").read_bytes()
    except OSError:
        return False
    arguments = command_line.decode("utf-8", "replace").split("\0")
    return "jinni" in arguments and socket_path in arguments


def _kill_child(process: subprocess.Popen[bytes]) -> None:
    process.kill()
    try:
        process.wait(timeout=_STOP_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        pass


def _kill_pid(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _pidfile(socket_path: str) -> Path:
    return Path(socket_path).with_name("jinni.pid")


def _write_pidfile(socket_path: str, pid: int) -> None:
    _pidfile(socket_path).write_text(str(pid))


def _read_pidfile(socket_path: str) -> int | None:
    try:
        return int(_pidfile(socket_path).read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def _clear_runtime_files(socket_path: str) -> None:
    _pidfile(socket_path).unlink(missing_ok=True)
    Path(socket_path).unlink(missing_ok=True)
