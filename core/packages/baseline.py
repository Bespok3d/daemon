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

STOCK_COPIES_DIR = "patches_orig"


def _strip_carriage_returns(text: str) -> bytes:
    return text.encode().replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _fragment_applies(work_path: Path, patch_file: Path, reverse: bool) -> bool:
    """Apply one fragment to the working copy in place and report whether it applied cleanly. `-f`
    keeps patch from guessing that an already-present change is a reversed patch, so a fragment that
    does not truly fit the file rejects instead of being silently skipped. `-F0` allows no fuzz:
    proving a file is these diffs' original means every context line matched, and a hunk placed by
    ignoring its context is exactly the unproven original that must never be adopted. Without it the
    answer depends on which patch the machine ships, which decided this one way on a maintainer's
    Mac and the other way on the Linux runner."""
    command = ["patch", "-f", "-F0", "--strip=1", str(work_path), str(patch_file)]
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


def is_stock(source_text: str, fragment_paths: list[Path]) -> bool:
    """Whether none of these diffs is on this text yet: they all still apply cleanly to it, so it is
    the original they were written against (or close enough to patch)."""
    return _probe(source_text, fragment_paths, reverse=False) is not None


def without_patches(source_text: str, fragment_paths: list[Path]) -> str | None:
    """This text with these diffs reversed back off it, or None when it is not their applied output.
    The recovered text is re-probed forward, so a reversal that lands on something the diffs no
    longer fit is reported as no recovery rather than passed off as the original."""
    recovered_stock = _probe(source_text, fragment_paths, reverse=True)
    if recovered_stock is None or not is_stock(recovered_stock, fragment_paths):
        return None
    return recovered_stock


def stock_copies(plugin_dir: Path) -> Path:
    """Where a plugin keeps the stock originals of the files it patches, one per target file."""
    return plugin_dir / STOCK_COPIES_DIR


def _mirrored_path(target_path: Path) -> Path:
    """The target's own path made relative, so the kept copies mirror the tree they were taken from
    and no two of them can land on the same name."""
    named_parts = [part for part in target_path.parts if part not in ("/", "..", ".")]
    return Path(*named_parts) if named_parts else Path(target_path.name)


def kept_original(orig_dir: Path, target: str | Path) -> Path:
    """Where a plugin keeps the stock original of ONE patched file.

    Keyed by the file's own path, because a printer holds more than one file of a given name: a
    plugin patching `moonraker/moonraker.conf` and `klipper/moonraker.conf` keyed by name alone
    would capture one over the other, and uninstall would then write the wrong file back over one
    of the two.

    A printer patched by an earlier daemon keeps its copies under the bare name, and that copy is
    the only record of what that file looked like stock. It is used wherever it is still there, so
    updating the daemon never orphans the copy the printer needs to get back to stock.
    """
    target_path = Path(target)
    kept_under_the_bare_name = orig_dir / target_path.name
    if kept_under_the_bare_name.is_file():
        return kept_under_the_bare_name
    return orig_dir / _mirrored_path(target_path)


def derive_stock(baseline_path: Path, fragment_paths: list[Path]) -> None:
    """Rewrite `baseline_path` to the stock original WHEN it is currently the already-patched output
    of these diffs, so the pipeline never patches an already-patched file. A file the diffs apply
    cleanly to is left as-is (it is stock, or close enough to patch). A file that is neither is left
    untouched too, so the normal apply reports its own reject instead of being pre-empted here."""
    source_text = baseline_path.read_text(errors="replace")
    if is_stock(source_text, fragment_paths):
        return
    recovered_stock = without_patches(source_text, fragment_paths)
    if recovered_stock is not None:
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
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
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
