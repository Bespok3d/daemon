# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The patch program this machine ships, and how to ask it to prove a fragment truly fits.

The CI runner carries GNU patch, a maintainer's Mac carries Apple's patch, and the printer carries
BusyBox patch. They do not take the same flags and they do not place a hunk the same way, so what
"strict" costs is asked of the machine rather than assumed, each hunk's context is evened out before
any of them sees it (see `hunk_context`), and every fragment goes through the one place that knows.
"""

import subprocess
from functools import lru_cache
from pathlib import Path

from .hunk_context import context_evened

# Fragments are read and handed on byte for byte, whatever encoding the file they patch uses.
FRAGMENT_ENCODING = ("utf-8", "surrogateescape")

# The exit status patch itself gives a diff it cannot read, so a missing fragment fails like one.
UNREADABLE_FRAGMENT = 2

# What stops GNU patch guessing and fuzzing. Asked for only where they are understood.
GNU_STRICTNESS = ("-f", "-F0")


@lru_cache(maxsize=1)
def strictness_flags() -> tuple[str, ...]:
    """The flags that make THIS machine's patch prove a fragment truly fits. Which flags those are
    depends on the patch the machine ships, so they are asked of it rather than assumed.

    GNU patch, what the CI runner carries, otherwise guesses that an already-present change is a
    reversed patch and places a hunk by ignoring its context. Either would pass off a file that is
    not these diffs' original as one. `-f` and `-F0` stop both. Apple's patch on a Mac takes the
    same two flags the same way.

    The printer carries BusyBox patch, which has neither behaviour to switch off and exits with
    "invalid option" on `-F`. Asked for them, every probe on the printer failed, and the daemon
    told a user with the true original on their machine that there was no original to adopt. Bare
    flags are already as strict there. GNU and Apple answer `patch --version` and exit 0; BusyBox
    does not.
    """
    version_answer = subprocess.run(["patch", "--version"], capture_output=True, check=False)
    return GNU_STRICTNESS if version_answer.returncode == 0 else ()


def run_fragment(
    work_path: Path, patch_file: Path, reverse: bool,
) -> subprocess.CompletedProcess[bytes]:
    """Put one fragment on the working copy in place (or take it off, reversed), as strictly as this
    machine's patch can be asked to be, with its hunks' context evened out. The diff goes in on
    stdin, which GNU, BusyBox and Apple patch all read when no diff file is named."""
    reversal = ["-R"] if reverse else []
    command = ["patch", *reversal, *strictness_flags(), "--strip=1", str(work_path)]
    try:
        fragment_text = patch_file.read_bytes().decode(*FRAGMENT_ENCODING)
    except OSError as unreadable:
        return subprocess.CompletedProcess(command, UNREADABLE_FRAGMENT,
                                           stdout=b"", stderr=str(unreadable).encode())
    evened = context_evened(fragment_text)
    return subprocess.run(command, input=evened.encode(*FRAGMENT_ENCODING),
                          capture_output=True, check=False)


def fragment_applies(work_path: Path, patch_file: Path, reverse: bool) -> bool:
    """Apply one fragment to the working copy in place and report whether it applied cleanly. A
    fragment that does not truly fit the file must reject rather than be silently skipped: proving a
    file is these diffs' original means every context line patch is handed matched. Near a file's
    start or end that is the evened context, not every line `diff` wrote (see `hunk_context`)."""
    result = run_fragment(work_path, patch_file, reverse)
    reject_path = work_path.parent / (work_path.name + ".rej")
    applied_cleanly = result.returncode == 0 and not reject_path.exists()
    reject_path.unlink(missing_ok=True)
    return applied_cleanly
