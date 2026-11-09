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


FEED_LINE = 'INFO:     10.6.9.4:55925 - "WebSocket /ws/install-progress?{credential}" [accepted]\n'
SERVER_START_LINE = "INFO:     Started server process [812]\n"
FEED_TOKEN = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
OLD_FEED_LINE = FEED_LINE.format(credential=f"token={FEED_TOKEN}")
SCRUBBED_FEED_LINE = FEED_LINE.format(credential="[token redacted]")
SCRUB_BOTH_LOGS = 'LOG_FILE="$1"; scrub_log_tokens "$1"; scrub_log_tokens "$1.prev"'


def scrub_through_the_script(daemon_log: Path) -> None:
    subprocess.run(
        ["sh", "-c", f". {INIT_SCRIPT}; {SCRUB_BOTH_LOGS}", "scrub", str(daemon_log)],
        env={"PATH": "/usr/bin:/bin"},
        check=True,
    )


def test_start_scrubs_the_tokens_older_daemons_wrote_into_both_logs(tmp_path: Path) -> None:
    daemon_log = tmp_path / "daemon.log"
    previous_log = tmp_path / "daemon.log.prev"
    daemon_log.write_text(OLD_FEED_LINE)
    previous_log.write_text(SERVER_START_LINE + OLD_FEED_LINE)
    previous_log.chmod(0o640)

    scrub_through_the_script(daemon_log)

    assert daemon_log.read_text() == SCRUBBED_FEED_LINE
    assert previous_log.read_text() == SERVER_START_LINE + SCRUBBED_FEED_LINE
    assert previous_log.stat().st_mode & 0o777 == 0o640
    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["daemon.log", "daemon.log.prev"]


def test_a_scrub_that_fails_keeps_the_log_and_says_so_in_the_daemon_log(tmp_path: Path) -> None:
    daemon_log = tmp_path / "daemon.log"
    unwritable_log = tmp_path / "daemon.log.prev"
    daemon_log.write_text("")
    unwritable_log.write_text(OLD_FEED_LINE)
    unwritable_log.chmod(0o444)

    scrub_through_the_script(daemon_log)

    assert unwritable_log.read_text() == OLD_FEED_LINE
    assert daemon_log.read_text() == (
        f"bespok3d: could not scrub access tokens from {unwritable_log}\n")
    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["daemon.log", "daemon.log.prev"]
