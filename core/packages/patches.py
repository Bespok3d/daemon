# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Patches: apply a plugin's unified diffs to stock source, with CRLF handling, legible failure
diagnostics, and a baseline of every original so teardown can restore it.

The stock file is FETCHED from the device through the jinni (reading a device file is the jinni's,
ADR-0037) and captured as the baseline in `patches_orig/`. Before any fragment touches it, that
baseline is self-healed back to stock when it is the already-patched output of these diffs (a
re-provision can leave the live file patched with no baseline held), so the plugin never traps
itself re-patching an already-patched file (see baseline.derive_stock). Every fragment targeting
that file is applied IN ORDER to one working copy of the baseline (pure daemon CPU), so a later
fragment builds on an earlier one (klipper-motion patches toolhead.py four times); the cumulative
result is WRITTEN back through the jinni once. `restore` writes the baseline back the same way.
"""

import re
import shutil
import subprocess
from pathlib import Path

from .. import jinni_client
from ..results import MAX_OUTPUT_BYTES, item, phase
from . import baseline
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


def _apply_fragment(work_path: Path, patch_file: Path, patch_rel: str, crlf_stripped: bool) -> dict:
    """Apply one diff fragment to the working copy IN PLACE, so the next fragment for the same file
    builds on it (the old in-place cumulative patching, now on a bespok3d-tree copy). The item is
    named for the fragment, so a conflict points at the exact diff to re-author."""
    result = subprocess.run(["patch", "-N", "--strip=1", str(work_path), str(patch_file)],
                            capture_output=True, check=False)
    raw = (result.stdout + result.stderr).decode(errors="replace") + _collect_rej(work_path)
    ok = result.returncode == 0
    context = _actual_context(work_path, patch_file, crlf_stripped) if not ok else ""
    raw += f"\n{context}" if context else ""
    output = raw[:MAX_OUTPUT_BYTES] + ("…" if len(raw) > MAX_OUTPUT_BYTES else "")
    return item(f"patch {Path(patch_rel).name}", ok=ok, output=output.strip())


def _write_back(target: Path, work_path: Path, pristine_path: Path, plugin_dir: Path, applied: bool) -> dict | None:  # noqa: E501
    """Write the cumulative patched content back to the device through the jinni once, only when
    EVERY fragment applied. One rejected fragment means the work copy is half edited, and a half
    edited Klipper file can stop the printer booting, so nothing reaches the device: the phase
    already fails on the rejected fragment and the caller rolls the install back from the untouched
    live file. Returns a failed item if the jinni write failed, so the install settles it."""
    if not applied:
        return None
    write = {"path": str(target), "content": work_path.read_text(errors="replace"),
             "restore_from": str(pristine_path)}
    written = jinni_client.write_files(str(plugin_dir), [write])
    if written[0].ok:
        return None
    return item(f"write {target.name}", ok=False, output=written[0].output)


def _patch_target(target: str, fragments: list[dict], plugin_dir: Path, vars: dict[str, str], orig_dir: Path) -> list[dict]:  # noqa: E501
    """Apply every fragment for ONE target file cumulatively, then write the result back once. The
    pristine baseline is fetched once and kept only for restore; the fragments build on a working
    copy of it, never re-applying against the original."""
    target_path = Path(target)
    pristine_path = baseline.kept_original(orig_dir, target_path)
    fragment_paths = [plugin_dir / fragment["patch"] for fragment in fragments]
    fetch_failure = baseline.establish(target_path, pristine_path, fragment_paths)
    if fetch_failure is not None:
        return [item(f"patch {Path(fragment['patch']).name}", ok=False, output=fetch_failure)
                for fragment in fragments]
    work_path = pristine_path.parent / (pristine_path.name + ".b3work")
    shutil.copy2(pristine_path, work_path)
    crlf_stripped = _normalize_line_endings(work_path)
    items = [_apply_fragment(work_path, plugin_dir / fragment["patch"], fragment["patch"], crlf_stripped)  # noqa: E501
             for fragment in fragments]
    write_failure = _write_back(target_path, work_path, pristine_path, plugin_dir,
                                all(fragment_item["ok"] for fragment_item in items))
    work_path.unlink(missing_ok=True)
    return [*items, write_failure] if write_failure else items


def _group_by_target(patches: list[dict], vars: dict[str, str]) -> dict[str, list[dict]]:
    """Fragments grouped by resolved target file, first-appearance order kept. Several fragments for
    one file apply cumulatively (see _patch_target)."""
    groups: dict[str, list[dict]] = {}
    for patch_def in patches:
        groups.setdefault(expand(patch_def["file"], vars), []).append(patch_def)
    return groups


def apply_patches(patches: list[dict], plugin_dir: Path, vars: dict[str, str]) -> dict:
    orig_dir = baseline.stock_copies(plugin_dir)
    orig_dir.mkdir(parents=True, exist_ok=True)
    items: list[dict] = []
    for target, fragments in _group_by_target(patches, vars).items():
        items.extend(_patch_target(target, fragments, plugin_dir, vars, orig_dir))
    return phase("patches", "Patches", items)


def restore_original_files(patches: list[dict], orig_dir: Path, vars: dict[str, str]) -> None:
    """Write each kept pristine baseline back over its target through the jinni, undoing the patch.
    Deduped by target: several fragments for one file share one baseline, so it is restored once.
    An empty kept baseline is skipped: a copy torn by a power cut mid capture would blank a file the
    printer boots from, and leaving the file patched is what a missing copy already does."""
    plugin_dir = orig_dir.parent
    writes = []
    seen: set[str] = set()
    for patch_def in patches:
        target = str(Path(expand(patch_def["file"], vars)))
        pristine_path = baseline.kept_original(orig_dir, target)
        pristine = pristine_path.read_text(errors="replace") if pristine_path.exists() else ""
        if target not in seen and pristine:
            seen.add(target)
            writes.append({"path": target, "content": pristine})
    if writes:
        jinni_client.write_files(str(plugin_dir), writes)
