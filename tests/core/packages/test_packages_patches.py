# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Patches (the unified-diff apply + CRLF handling + original-file backup/restore) have a canonical
home in core.packages.patches. These guard the diagnostics that make a failed patch legible and the
restore that teardown relies on."""
from pathlib import Path

from core.packages import baseline, patches

STOCK = "alpha\nbeta\ngamma\ndelta\nepsilon\n"
PATCHED = "alpha\nbeta2\ngamma\ndelta2\nepsilon\n"
BETA_FRAGMENT = (
    "--- a/mod.py\n+++ b/mod.py\n@@ -1,5 +1,5 @@\n"
    " alpha\n-beta\n+beta2\n gamma\n delta\n epsilon\n"
)
DELTA_FRAGMENT = (
    "--- a/mod.py\n+++ b/mod.py\n@@ -1,5 +1,5 @@\n"
    " alpha\n beta2\n gamma\n-delta\n+delta2\n epsilon\n"
)


def _write_fragments(fragment_dir: Path) -> list[Path]:
    """The two cumulative fragments klipper-motion-style: DELTA_FRAGMENT's context carries BETA's
    output, so it only applies after BETA and only reverses before it (order matters both ways)."""
    fragment_dir.mkdir(parents=True, exist_ok=True)
    first = fragment_dir / "01-beta.patch"
    second = fragment_dir / "02-delta.patch"
    first.write_text(BETA_FRAGMENT)
    second.write_text(DELTA_FRAGMENT)
    return [first, second]


def test_normalize_line_endings_strips_crlf(tmp_path: Path) -> None:
    target = tmp_path / "win.cfg"
    target.write_bytes(b"a\r\nb\r\n")
    assert patches._normalize_line_endings(target) is True
    assert target.read_bytes() == b"a\nb\n"


def test_normalize_line_endings_is_noop_without_carriage_return(tmp_path: Path) -> None:
    target = tmp_path / "unix.cfg"
    target.write_bytes(b"a\nb\n")
    assert patches._normalize_line_endings(target) is False


def test_actual_context_returns_numbered_window(tmp_path: Path) -> None:
    target = tmp_path / "src.py"
    target.write_text("".join(f"line{n}\n" for n in range(1, 11)))
    patch_file = tmp_path / "p.patch"
    patch_file.write_text("@@ -3,2 +3,2 @@\n")
    context = patches._actual_context(target, patch_file)
    assert "actual file" in context
    assert "line3" in context


def test_actual_context_empty_when_target_missing(tmp_path: Path) -> None:
    assert patches._actual_context(tmp_path / "absent", tmp_path / "p.patch") == ""


def test_collect_rej_reads_and_removes_reject_file(tmp_path: Path) -> None:
    work = tmp_path / "src.py.b3work"
    work.write_text("working copy\n")
    rej = tmp_path / "src.py.b3work.rej"
    rej.write_text("hunk #1 FAILED\n")
    collected = patches._collect_rej(work)
    assert "rejected hunks" in collected
    assert "hunk #1 FAILED" in collected
    assert not rej.exists()


def test_collect_rej_empty_when_no_reject(tmp_path: Path) -> None:
    assert patches._collect_rej(tmp_path / "src.py.b3work") == ""


def test_restore_original_files_copies_backup_over_target(tmp_path: Path) -> None:
    orig_dir = tmp_path / "patches_orig"
    orig_dir.mkdir()
    (orig_dir / "toolhead.py").write_text("stock\n")
    target = tmp_path / "klippy" / "toolhead.py"
    target.parent.mkdir()
    target.write_text("patched\n")
    patches.restore_original_files([{"file": str(target)}], orig_dir, {})
    assert target.read_text() == "stock\n"


def test_derive_stock_leaves_a_stock_baseline_untouched(tmp_path: Path) -> None:
    baseline_file = tmp_path / "mod.py"
    baseline_file.write_text(STOCK)
    fragments = _write_fragments(tmp_path / "patches")
    baseline.derive_stock(baseline_file, fragments)
    assert baseline_file.read_text() == STOCK


def test_derive_stock_recovers_an_already_patched_baseline(tmp_path: Path) -> None:
    """The field trap: the captured baseline is itself the fully-patched file. derive_stock reverses
    the fragments to recover the stock original and rewrites the baseline to it, so the pipeline
    never patches an already-patched file and disables the plugin."""
    baseline_file = tmp_path / "mod.py"
    baseline_file.write_text(PATCHED)
    fragments = _write_fragments(tmp_path / "patches")
    baseline.derive_stock(baseline_file, fragments)
    assert baseline_file.read_text() == STOCK


def test_derive_stock_leaves_an_unrecoverable_baseline_untouched(tmp_path: Path) -> None:
    """A file that is neither stock nor the reversible patched output is left as-is, for the normal
    apply to diagnose with an actual-file reject rather than being pre-empted or corrupted here."""
    baseline_file = tmp_path / "mod.py"
    baseline_file.write_text("wholly unrelated content\n")
    fragments = _write_fragments(tmp_path / "patches")
    baseline.derive_stock(baseline_file, fragments)
    assert baseline_file.read_text() == "wholly unrelated content\n"


def test_apply_patches_self_heals_a_reprovisioned_device(tmp_path: Path) -> None:
    """Full field repro: a re-provision wiped patches_orig and left the live Klipper file already
    patched. apply_patches fetches that file, recovers stock, applies cleanly, and leaves a
    stock baseline so a later teardown restores the true original. On the old pipeline the fetched
    patched file became the permanent baseline and every re-install failed with a hunk reject."""
    plugin_dir = tmp_path / "plugin"
    _write_fragments(plugin_dir / "patches")
    target = tmp_path / "klippy" / "mod.py"
    target.parent.mkdir(parents=True)
    target.write_text(PATCHED)
    patch_defs = [
        {"file": str(target), "patch": "patches/01-beta.patch"},
        {"file": str(target), "patch": "patches/02-delta.patch"},
    ]
    result = patches.apply_patches(patch_defs, plugin_dir, {})
    assert result["ok"] is True
    assert target.read_text() == PATCHED
    kept = baseline.kept_original(baseline.stock_copies(plugin_dir), target)
    assert kept.read_text() == STOCK


def test_apply_patches_leaves_a_foreign_file_untouched(tmp_path: Path) -> None:
    """A live file that is neither stock nor the reversible patched output cannot be reconciled:
    every fragment rejects, so apply_patches fails and writes nothing back, leaving the device file
    intact (the printer is never left broken) with the reject diagnostic to explain it."""
    plugin_dir = tmp_path / "plugin"
    _write_fragments(plugin_dir / "patches")
    target = tmp_path / "klippy" / "mod.py"
    target.parent.mkdir(parents=True)
    target.write_text("wholly unrelated content\n")
    patch_defs = [
        {"file": str(target), "patch": "patches/01-beta.patch"},
        {"file": str(target), "patch": "patches/02-delta.patch"},
    ]
    result = patches.apply_patches(patch_defs, plugin_dir, {})
    assert result["ok"] is False
    assert target.read_text() == "wholly unrelated content\n"
