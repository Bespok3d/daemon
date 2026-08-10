# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The staged package must arm b3-builder's wheel bake, or the printer goes to pypi at enrollment.

b3-builder bakes a package's Python deps only when it finds requirements.txt at the package ROOT
(ADR-0036, presence-driven). The staging script also puts a copy inside files/, which is the list
the venv provisioning reads back on the printer. Losing the root copy disarms the bake silently:
the build stays green and the .b3 ships with no wheels, so the printer tries to reach the network
for them. This runs the real staging script and asserts both copies, so a disarmed bake is caught.
"""

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STAGING_SCRIPT = REPO_ROOT / "scripts" / "stage-package.sh"


def staged_package_dir() -> Path:
    subprocess.run(["sh", str(STAGING_SCRIPT)], cwd=REPO_ROOT, check=True, capture_output=True)
    package_name: str = json.loads((REPO_ROOT / "manifest.json").read_text())["name"]
    return REPO_ROOT / "dist" / "package" / package_name


def test_requirements_is_staged_at_the_package_root_where_the_bake_reads_it() -> None:
    package = staged_package_dir()

    assert (package / "requirements.txt").is_file(), "the wheel bake is disarmed without this copy"


def test_requirements_is_also_staged_inside_files_for_the_printer() -> None:
    package = staged_package_dir()

    assert (package / "files" / "requirements.txt").is_file()


def test_no_wheels_are_staged_by_hand_because_the_bake_owns_that_payload() -> None:
    package = staged_package_dir()

    assert not (package / "files" / "wheels").exists()
