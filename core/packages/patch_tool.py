# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The patch program this machine ships, and how to ask it to prove a fragment truly fits.

A maintainer's Mac and the CI runner carry GNU patch; the printer carries BusyBox patch. They do
not take the same flags and they do not guess the same way, so what "strict" costs is asked of the
machine rather than assumed, and every fragment goes through the one place that knows.
"""

import subprocess
from functools import lru_cache
from pathlib import Path

# What stops GNU patch guessing and fuzzing. Asked for only where they are understood.
GNU_STRICTNESS = ("-f", "-F0")


@lru_cache(maxsize=1)
def strictness_flags() -> tuple[str, ...]:
    """The flags that make THIS machine's patch prove a fragment truly fits. Which flags those are
    depends on the patch the machine ships, so they are asked of it rather than assumed.

    GNU patch, what a maintainer's Mac and the CI runner carry, otherwise guesses that an
    already-present change is a reversed patch and places a hunk by ignoring its context. Either
    would pass off a file that is not these diffs' original as one. `-f` and `-F0` stop both.

    The printer carries BusyBox patch, which has neither behaviour to switch off and exits with
    "invalid option" on `-F`. Asked for them, every probe on the printer failed, and the daemon
    told a user with the true original on their machine that there was no original to adopt. Bare
    flags are already as strict there. GNU answers `patch --version` and exits 0; BusyBox does not.
    """
    version_answer = subprocess.run(["patch", "--version"], capture_output=True, check=False)
    return GNU_STRICTNESS if version_answer.returncode == 0 else ()


def fragment_applies(work_path: Path, patch_file: Path, reverse: bool) -> bool:
    """Apply one fragment to the working copy in place and report whether it applied cleanly, as
    strictly as this machine's patch can be asked to be (see `strictness_flags`). A fragment that
    does not truly fit the file must reject rather than be silently skipped: proving a file is these
    diffs' original means every context line matched."""
    reversal = ["-R"] if reverse else []
    command = ["patch", *reversal, *strictness_flags(), "--strip=1",
               str(work_path), str(patch_file)]
    result = subprocess.run(command, capture_output=True, check=False)
    reject_path = work_path.parent / (work_path.name + ".rej")
    applied_cleanly = result.returncode == 0 and not reject_path.exists()
    reject_path.unlink(missing_ok=True)
    return applied_cleanly
