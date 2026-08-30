# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The baseline probe run against the patch a real printer carries, not the one a laptop carries.

The probe proves a file is (or is not) these diffs' original by running them over a copy of it. How
strict it can ask patch to be depends on the patch that machine ships: the printer's BusyBox patch
refuses the flags GNU patch needs to be told, and asked for them it refuses every probe, so a
printer holding the true original was told there was no original to adopt.
"""
import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from core.packages import baseline, patch_tool

STOCK = "alpha\nbeta\ngamma\ndelta\nepsilon\n"
PATCHED = "alpha\nbeta2\ngamma\ndelta\nepsilon\n"
BETA_FRAGMENT = (
    "--- a/mod.py\n+++ b/mod.py\n@@ -1,5 +1,5 @@\n"
    " alpha\n-beta\n+beta2\n gamma\n delta\n epsilon\n"
)
BUSYBOX_SHIM = """#!/bin/sh
for arg in "$@"; do
  case "$arg" in
    --version|-f|-F*) echo "patch: invalid option -- '$arg'" >&2; exit 1 ;;
  esac
done
exec {real_patch} "$@"
"""
RECORDING_SHIM = """#!/bin/sh
echo "$@" >> {record}
exec {real_patch} "$@"
"""


@pytest.fixture(autouse=True)
def forget_the_patch_already_detected() -> Iterator[None]:
    """Which patch is on PATH is answered once and remembered, so each test asks again."""
    patch_tool.strictness_flags.cache_clear()
    yield
    patch_tool.strictness_flags.cache_clear()


def _patch_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, script: str) -> None:
    shim_dir = tmp_path / "shim-bin"
    shim_dir.mkdir()
    shim = shim_dir / "patch"
    shim.write_text(script.format(real_patch=shutil.which("patch"), record=tmp_path / "invoked"))
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{shim_dir}{os.pathsep}{os.environ['PATH']}")


def _fragment(tmp_path: Path) -> list[Path]:
    fragment_path = tmp_path / "01-beta.patch"
    fragment_path.write_text(BETA_FRAGMENT)
    return [fragment_path]


def test_the_probe_reads_a_stock_file_as_stock_on_the_printers_patch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The printer's patch refuses the strictness flags outright. The probe must still answer about
    the file, or every adopt on a printer fails with no original to adopt."""
    _patch_on_path(tmp_path, monkeypatch, BUSYBOX_SHIM)

    assert baseline.is_stock(STOCK, _fragment(tmp_path)) is True


def test_the_probe_recovers_the_original_from_a_patched_file_on_the_printers_patch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of adopt on a printer: reversing the diffs off the live file gives back the
    original the new owner is entitled to."""
    _patch_on_path(tmp_path, monkeypatch, BUSYBOX_SHIM)

    assert baseline.without_patches(PATCHED, _fragment(tmp_path)) == STOCK


def test_the_probe_still_forbids_fuzz_where_the_patch_understands_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hunk placed by ignoring its context is exactly the unproven original that must never be
    adopted, so the machines whose patch can be told that are still told it."""
    _patch_on_path(tmp_path, monkeypatch, RECORDING_SHIM)

    baseline.is_stock(STOCK, _fragment(tmp_path))

    invocations = (tmp_path / "invoked").read_text().splitlines()
    assert any("-F0" in line and "-f" in line for line in invocations)
