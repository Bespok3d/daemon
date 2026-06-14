"""Unpacking a .b3 package: read its manifest, extract its file tree onto the printer, and fix the
permissions. A .b3 is a zip of manifest.json plus the plugin's files; doc/ is catalog-only and never
deployed (printer space is at a premium).

unpack_package brackets the extraction with the two safety checks that belong to it: refuse
mid-print before touching disk, and validate the plugin's baked Python deps right after.
"""

import json
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import cast

from ..results import item, phase
from .print_guard import guard_no_print_during_restart
from .python_deps import reject_conflicting_dep_files, reject_unbaked_deps


def read_manifest(package_path: Path) -> dict:
    with zipfile.ZipFile(package_path) as zf:
        return cast(dict, json.loads(zf.read("manifest.json")))


def _is_doc_member(name: str) -> bool:
    return name == "doc" or name.startswith("doc/")


def _extract_members(zf: zipfile.ZipFile, plugin_dir: Path, members: list[str]) -> None:
    # Unlink an existing file before extracting over it. Overwriting a running binary in place fails
    # with ETXTBSY ("Text file busy"); unlinking keeps the running process's inode and writes a new
    # file, so a reinstall or version switch can replace a binary that is currently executing.
    for name in members:
        dest = plugin_dir / name
        if dest.is_file() or dest.is_symlink():
            dest.unlink()
        zf.extract(name, plugin_dir)


def unpack_package(plugin_root: Path, package_path: Path) -> tuple[dict, Path, int]:
    with zipfile.ZipFile(package_path) as zf:
        if "manifest.json" not in zf.namelist():
            raise ValueError("missing manifest.json")
        manifest = json.loads(zf.read("manifest.json"))
        guard_no_print_during_restart(manifest)
        plugin_dir = plugin_root / manifest["name"]
        plugin_dir.mkdir(parents=True, exist_ok=True)
        members = [name for name in zf.namelist() if not _is_doc_member(name)]
        _extract_members(zf, plugin_dir, members)
        file_count = len(members)
    shutil.rmtree(plugin_dir / "doc", ignore_errors=True)
    reject_conflicting_dep_files(plugin_dir)
    reject_unbaked_deps(plugin_dir)
    return manifest, plugin_dir, file_count


def fix_ownership(plugin_dir: Path, runtime_user: str) -> dict:
    items: list[dict] = []
    chmod_result = subprocess.run(
        ["chmod", "-R", "755", str(plugin_dir)], capture_output=True, check=False,
    )
    items.append(item(f"chmod -R 755 {plugin_dir.name}", ok=chmod_result.returncode == 0))
    if runtime_user:
        chown_result = subprocess.run(
            ["chown", "-R", f"{runtime_user}:{runtime_user}", str(plugin_dir)],
            capture_output=True,
            check=False,
        )
        items.append(item(
            f"chown -R {runtime_user} {plugin_dir.name}",
            ok=chown_result.returncode == 0,
        ))
    return phase("ownership", "Permissions", items)
