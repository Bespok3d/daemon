"""Patches: apply a plugin's unified diffs to stock source, with CRLF handling, legible failure
diagnostics, and a backup of every original so teardown can restore it.

Each target is patched on a working copy via the `patch` binary; the pristine original is copied
into the plugin's `patches_orig/` the first time so `restore_original_files` can put it back.
"""

import re
import shutil
import subprocess
from pathlib import Path

from ..results import MAX_OUTPUT_BYTES, item, phase
from .user_vars import expand


def _normalize_line_endings(path: Path) -> bool:
    content = path.read_bytes()
    if b'\r' not in content:
        return False
    path.write_bytes(content.replace(b'\r\n', b'\n').replace(b'\r', b'\n'))
    return True


def _actual_context(target: Path, patch_file: Path, crlf_was_stripped: bool = False) -> str:
    if not target.exists():
        return ""
    text = patch_file.read_text(errors="replace")
    match = re.search(r"@@ -(\d+)", text)
    if not match:
        return ""
    start_line = int(match.group(1))
    lines = target.read_text(errors="replace").splitlines()
    window_start = max(0, start_line - 6)
    window_end = min(len(lines), start_line + 20)
    numbered = "\n".join(
        f"{window_start + line_offset + 1:4d}  {lines[window_start + line_offset]}"
        for line_offset in range(window_end - window_start)
    )
    note = " [CRLF stripped before patch]" if crlf_was_stripped else ""
    return f"--- actual file (lines {window_start + 1}-{window_end}){note} ---\n{numbered}"


def _collect_rej(work_path: Path) -> str:
    rej_path = work_path.parent / (work_path.name + ".rej")
    if not rej_path.exists():
        return ""
    rej_text = rej_path.read_text(errors="replace")
    rej_path.unlink(missing_ok=True)
    return f"\n--- rejected hunks ---\n{rej_text}"


def _apply_one_patch(target: Path, patch_file: Path, orig_dir: Path) -> tuple[bool, str]:
    orig_path = orig_dir / target.name
    if not orig_path.exists():
        shutil.copy2(target, orig_path)
    work_path = target.parent / (target.name + ".b3work")
    shutil.copy2(target, work_path)
    crlf_stripped = _normalize_line_endings(work_path)
    result = subprocess.run(
        ["patch", "-N", "--strip=1", str(work_path), str(patch_file)],
        capture_output=True,
        check=False,
    )
    raw = (result.stdout + result.stderr).decode(errors="replace")
    raw += _collect_rej(work_path)
    if result.returncode == 0:
        shutil.copy2(work_path, target)
    else:
        ctx = _actual_context(work_path, patch_file, crlf_stripped)
        if ctx:
            raw += f"\n{ctx}"
    work_path.unlink(missing_ok=True)
    return result.returncode == 0, raw


def apply_patches(patches: list[dict], plugin_dir: Path, vars: dict[str, str]) -> dict:
    items: list[dict] = []
    orig_dir = plugin_dir / "patches_orig"
    orig_dir.mkdir(parents=True, exist_ok=True)
    for patch_def in patches:
        target = Path(expand(patch_def["file"], vars))
        patch_file = plugin_dir / patch_def["patch"]
        label = f"patch {target.name}"
        if not target.exists():
            items.append(item(label, ok=False, output="target file not found"))
            continue
        ok, raw = _apply_one_patch(target, patch_file, orig_dir)
        output = raw[:MAX_OUTPUT_BYTES] + ("…" if len(raw) > MAX_OUTPUT_BYTES else "")
        items.append(item(label, ok=ok, output=output.strip()))
    return phase("patches", "Patches", items)


def restore_original_files(patches: list[dict], orig_dir: Path, vars: dict[str, str]) -> None:
    for patch_def in patches:
        target = Path(expand(patch_def["file"], vars))
        orig_path = orig_dir / target.name
        if orig_path.exists():
            shutil.copy2(orig_path, target)
