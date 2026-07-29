# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Establish the STOCK baseline a plugin's diffs are applied to, self-healing a file that is already
patched.

The patch pipeline needs the original, unpatched file as its baseline. The device file it captures
is normally stock, but after a re-provision or a failed recovery the captured baseline (or the live
file it is captured from) can already carry a previous apply. Patching that again fails on every
retry and silently disables the plugin. `derive_stock` recovers from exactly that: when the baseline
is the already-patched output of these diffs, it reverses them to recover the stock original and
rewrites the baseline in place. A file the diffs already apply cleanly to (stock, or close enough)
is left as-is, and a file that is neither is also left untouched for the normal apply to diagnose
with an actual-file reject, so a plugin author still sees why their patch did not fit.
"""

import subprocess
import tempfile
from pathlib import Path

from .. import jinni_client


def _strip_carriage_returns(text: str) -> bytes:
    return text.encode().replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _fragment_applies(work_path: Path, patch_file: Path, reverse: bool) -> bool:
    """Apply one fragment to the working copy in place and report whether it applied cleanly. `-f`
    keeps patch from guessing that an already-present change is a reversed patch, so a fragment that
    does not truly fit the file rejects instead of being silently skipped."""
    command = ["patch", "-f", "--strip=1", str(work_path), str(patch_file)]
    if reverse:
        command.insert(1, "-R")
    result = subprocess.run(command, capture_output=True, check=False)
    reject_path = work_path.parent / (work_path.name + ".rej")
    applied_cleanly = result.returncode == 0 and not reject_path.exists()
    reject_path.unlink(missing_ok=True)
    return applied_cleanly


def _probe(source_text: str, fragment_paths: list[Path], reverse: bool) -> str | None:
    """Run every fragment over a throwaway copy of the source and return the result only if all of
    them applied cleanly, else None. Reversing un-applies in reverse order, so a patched file lands
    back on its original."""
    ordered = list(reversed(fragment_paths)) if reverse else fragment_paths
    with tempfile.TemporaryDirectory() as scratch_dir:
        work_path = Path(scratch_dir) / "baseline-probe"
        work_path.write_bytes(_strip_carriage_returns(source_text))
        applied = all(_fragment_applies(work_path, patch_file, reverse) for patch_file in ordered)
        return work_path.read_text(errors="replace") if applied else None


def derive_stock(baseline_path: Path, fragment_paths: list[Path]) -> None:
    """Rewrite `baseline_path` to the stock original WHEN it is currently the already-patched output
    of these diffs, so the pipeline never patches an already-patched file. A file the diffs apply
    cleanly to is left as-is (it is stock, or close enough to patch). A file that is neither is left
    untouched too, so the normal apply reports its own reject instead of being pre-empted here."""
    source_text = baseline_path.read_text(errors="replace")
    if _probe(source_text, fragment_paths, reverse=False) is not None:
        return
    recovered_stock = _probe(source_text, fragment_paths, reverse=True)
    if recovered_stock is not None and _probe(recovered_stock, fragment_paths, reverse=False) is not None:  # noqa: E501
        baseline_path.write_text(recovered_stock)


def _capture_if_absent(target: Path, baseline_path: Path) -> str | None:
    """Fetch the device's current file as the baseline candidate when none is held yet, through the
    jinni (reading a device file is the jinni's job). Returns a failure message when the device file
    is absent, else None. On a re-apply the candidate already exists and is kept for vetting."""
    if baseline_path.exists():
        return None
    content = jinni_client.fetch(str(target))
    if content is None:
        return "target file not found"
    baseline_path.write_text(content)
    return None


def establish(target: Path, baseline_path: Path, fragment_paths: list[Path]) -> str | None:
    """Put a usable stock baseline at `baseline_path` before any fragment touches it: capture the
    device file when none is held yet, then self-heal it to stock via derive_stock when it is the
    already-patched output of these diffs, so a re-provision never traps the plugin re-patching an
    already-patched file. Returns a failure message when the device file is missing, else None."""
    fetch_failure = _capture_if_absent(target, baseline_path)
    if fetch_failure is not None:
        return fetch_failure
    derive_stock(baseline_path, fragment_paths)
    return None
