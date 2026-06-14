"""Patches (the unified-diff apply + CRLF handling + original-file backup/restore) have a canonical
home in core.packages.patches. These guard the diagnostics that make a failed patch legible and the
restore that teardown relies on."""
from pathlib import Path

from core.packages import patches


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
