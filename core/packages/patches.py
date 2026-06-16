"""Patches: apply a plugin's unified diffs to stock source, with CRLF handling, legible failure
diagnostics, and a baseline of every original so teardown can restore it.

The stock file is FETCHED from the device through the jinni (reading a device file is the jinni's,
ADR-0037), captured once as the pristine baseline in the plugin's `patches_orig/`. The diff is
applied to a working copy of that baseline in the bespok3d tree (pure daemon CPU), and the patched
result is WRITTEN back through the jinni (writing a device file is its actuation). `restore` writes
the pristine baseline back the same way; the jinni records the restore reversion as it writes.
"""

import re
import shutil
import subprocess
from pathlib import Path

from .. import jinni_client
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


def _ensure_pristine(target: Path, pristine_path: Path) -> bool:
    """Capture the device's REAL current file as the pristine baseline, once, via the jinni's fetch.
    Returns False when the file is absent (so the patch reports target-not-found). On a re-apply the
    baseline already exists and is kept (the target is by then our patched copy)."""
    if pristine_path.exists():
        return True
    content = jinni_client.fetch(str(target))
    if content is None:
        return False
    pristine_path.write_text(content)
    return True


def _build_patched_content(pristine_path: Path, patch_file: Path) -> tuple[bool, str, str]:
    """Apply the diff to a working copy of the pristine baseline (pure daemon CPU on a bespok3d-tree
    file). Returns (ok, patched_content, diagnostics)."""
    work_path = pristine_path.parent / (pristine_path.name + ".b3work")
    shutil.copy2(pristine_path, work_path)
    crlf_stripped = _normalize_line_endings(work_path)
    result = subprocess.run(
        ["patch", "-N", "--strip=1", str(work_path), str(patch_file)],
        capture_output=True,
        check=False,
    )
    raw = (result.stdout + result.stderr).decode(errors="replace") + _collect_rej(work_path)
    ok = result.returncode == 0
    content = work_path.read_text(errors="replace") if ok else ""
    if not ok:
        ctx = _actual_context(work_path, patch_file, crlf_stripped)
        if ctx:
            raw += f"\n{ctx}"
    work_path.unlink(missing_ok=True)
    return ok, content, raw


def _patch_one(patch_def: dict, plugin_dir: Path, vars: dict[str, str], orig_dir: Path) -> dict:
    target = Path(expand(patch_def["file"], vars))
    patch_file = plugin_dir / patch_def["patch"]
    label = f"patch {target.name}"
    pristine_path = orig_dir / target.name
    if not _ensure_pristine(target, pristine_path):
        return item(label, ok=False, output="target file not found")
    ok, content, raw = _build_patched_content(pristine_path, patch_file)
    output = raw[:MAX_OUTPUT_BYTES] + ("…" if len(raw) > MAX_OUTPUT_BYTES else "")
    if not ok:
        return item(label, ok=False, output=output.strip())
    write = {"path": str(target), "content": content, "restore_from": str(pristine_path)}
    written = jinni_client.write_files(str(plugin_dir), [write])
    if not written[0].ok:
        return item(label, ok=False, output=written[0].output)
    return item(label, ok=True, output=output.strip())


def apply_patches(patches: list[dict], plugin_dir: Path, vars: dict[str, str]) -> dict:
    orig_dir = plugin_dir / "patches_orig"
    orig_dir.mkdir(parents=True, exist_ok=True)
    items = [_patch_one(patch_def, plugin_dir, vars, orig_dir) for patch_def in patches]
    return phase("patches", "Patches", items)


def restore_original_files(patches: list[dict], orig_dir: Path, vars: dict[str, str]) -> None:
    """Write each kept pristine baseline back over its target through the jinni, undoing the patch."""  # noqa: E501
    plugin_dir = orig_dir.parent
    writes = []
    for patch_def in patches:
        target = Path(expand(patch_def["file"], vars))
        pristine_path = orig_dir / target.name
        if pristine_path.exists():
            writes.append({"path": str(target), "content": pristine_path.read_text(errors="replace")})  # noqa: E501
    if writes:
        jinni_client.write_files(str(plugin_dir), writes)
