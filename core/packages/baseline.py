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

from pathlib import Path

import bespok3d_patch

from .. import jinni_client


def _strip_carriage_returns(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _fragment_applies(working_text: str, patch_file: Path, reverse: bool) -> str | None:
    """Apply one fragment to the in-memory working text and return the result text when it applied
    cleanly, else None. `reverse` un-applies the fragment, matching the old `-R` flag."""
    hunks = bespok3d_patch.parse_unified_diff(patch_file.read_text(errors="replace"))
    result = bespok3d_patch.apply(hunks, working_text, reverse=reverse)
    return result.text if result.applied else None


def _probe(source_text: str, fragment_paths: list[Path], reverse: bool) -> str | None:
    """Run every fragment over the source text and return the result only if all of them applied
    cleanly, else None. Reversing un-applies in reverse order, so a patched file lands back on its
    original."""
    ordered = list(reversed(fragment_paths)) if reverse else fragment_paths
    working_text = _strip_carriage_returns(source_text)
    for patch_file in ordered:
        working_text_or_none = _fragment_applies(working_text, patch_file, reverse)
        if working_text_or_none is None:
            return None
        working_text = working_text_or_none
    return working_text


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
