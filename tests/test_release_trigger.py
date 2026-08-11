# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A daemon release is published by a `daemon-v<version>` tag, and by nothing else.

The release workflow signs a package and registers its atom in the org index, which is what makes
the app offer that daemon to every enrolled printer. On a branch trigger any commit that lands
becomes an offered update, work in progress included, so the trigger shape is a release-safety
invariant and is tested here rather than left to review.

The tag-versus-DAEMON_VERSION guard is driven end-to-end as the workflow drives it, so the exit
code the run keys on is what these tests assert.
"""
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
GUARD = REPO_ROOT / "scripts" / "tag_version_guard.py"


def release_triggers() -> dict[str, Any]:
    """The workflow's `on:` block. YAML 1.1 reads a bare `on` as the boolean true, so the key this
    comes back under is True and not the string."""
    workflow = yaml.safe_load(RELEASE_WORKFLOW.read_text())
    return dict(workflow[True])


def run_guard(ref_name: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GUARD), ref_name],
        capture_output=True, text=True, timeout=30, check=False,
    )


def test_the_release_fires_on_a_daemon_version_tag() -> None:
    assert release_triggers()["push"]["tags"] == ["daemon-v*"]


def test_no_branch_push_can_publish_a_daemon() -> None:
    """A branch trigger turns every merged commit into an update offered to enrolled printers."""
    push_trigger = release_triggers()["push"]

    assert "branches" not in push_trigger
    assert "branches-ignore" not in push_trigger


def test_a_manual_run_reaches_the_version_guard() -> None:
    """The Run workflow button has to work. A job level `if: github.event_name == 'push'` made a
    manual run skip the whole job and report success, so a maintainer re-running a failed publish
    believed it went out when it did not. The version guard decides instead."""
    workflow = yaml.safe_load(RELEASE_WORKFLOW.read_text())

    assert "if" not in workflow["jobs"]["build-and-release"]


def test_a_tag_matching_the_declared_version_is_accepted() -> None:
    from version import DAEMON_VERSION

    assert run_guard(f"daemon-v{DAEMON_VERSION}").returncode == 0


def test_a_tag_disagreeing_with_the_declared_version_is_refused() -> None:
    result = run_guard("daemon-v99.99.99")

    assert result.returncode == 1
    assert "99.99.99" in result.stderr


def test_a_branch_ref_is_refused() -> None:
    """The other half of the manual run decision: with no job level `if` to skip the run, a Run
    workflow click off a branch is refused loudly by the guard rather than reported as a success."""
    result = run_guard("main")

    assert result.returncode == 1
    assert "daemon-v" in result.stderr
