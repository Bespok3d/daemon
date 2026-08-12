# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The init script signals only its own daemon.

Its pidfile sits under /userdata, which survives a reboot, so on the next start the number in it
belongs to whatever process the kernel handed it to next. These run the script's guard against a
real process with a made-up entry in the process table and check which one is still alive after.
"""
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

INIT_SCRIPT = Path(__file__).resolve().parents[1] / "s10bespok3d-daemon"
DAEMON_COMMAND = [
    "/userdata/bespok3d/venv/bin/python3",
    "/userdata/bespok3d/var/lib/daemon/daemon.py",
]
ENROLLMENT_CHECK_COMMAND = ["sh", "-c", "sleep 5 && kill -0 $(cat bespok3d-daemon.pid)"]


@pytest.fixture
def bystander() -> Iterator[subprocess.Popen[bytes]]:
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    yield process
    process.kill()
    process.wait()


def signal_through_the_script(process_table: Path, pid: int) -> None:
    subprocess.run(
        ["sh", "-c", f". {INIT_SCRIPT}; kill_if_our_daemon {pid}"],
        env={"PROC_ROOT": str(process_table), "PATH": "/usr/bin:/bin"},
        check=True,
    )


def record_running(process_table: Path, pid: int, arguments: list[str]) -> None:
    entry = process_table / str(pid)
    entry.mkdir(parents=True)
    (entry / "cmdline").write_bytes("\0".join([*arguments, ""]).encode())


def test_it_stops_a_daemon_the_pidfile_still_names(
    tmp_path: Path, bystander: subprocess.Popen[bytes],
) -> None:
    record_running(tmp_path, bystander.pid, DAEMON_COMMAND)

    signal_through_the_script(tmp_path, bystander.pid)

    assert bystander.wait(timeout=5) is not None


def test_it_spares_the_process_a_reboot_gave_that_number_to(
    tmp_path: Path, bystander: subprocess.Popen[bytes],
) -> None:
    record_running(tmp_path, bystander.pid, ENROLLMENT_CHECK_COMMAND)

    signal_through_the_script(tmp_path, bystander.pid)

    with pytest.raises(subprocess.TimeoutExpired):
        bystander.wait(timeout=1)
