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
from .integrity import (
    ESCAPING_MEMBER,
    UNDECLARED_MEMBER,
    IntegrityError,
)
from .members import (
    escaping_members,
    is_doc_member,
    undeclared_members,
)
from .plugin_dir import contained_plugin_dir
from .print_guard import guard_no_print_during_restart
from .python_deps import reject_conflicting_dep_files, reject_unbaked_deps


def read_manifest(package_path: Path) -> dict:
    with zipfile.ZipFile(package_path) as zf:
        return cast(dict, json.loads(zf.read("manifest.json")))


def _extract_members(
    zf: zipfile.ZipFile, plugin_dir: Path, plugin_id: str, members: list[str],
) -> None:
    escaping = escaping_members(plugin_dir, members)
    if escaping:
        raise IntegrityError(plugin_id, ESCAPING_MEMBER, escaping)
    # Unlink an existing file before extracting over it. Overwriting a running binary in place fails
    # with ETXTBSY ("Text file busy"); unlinking keeps the running process's inode and writes a new
    # file, so a reinstall or version switch can replace a binary that is currently executing. The
    # delete runs as root, which is why no member reaches it before the containment check above.
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
        # Checked before anything is measured against the plugin dir: the package names that
        # directory, so a name carrying a path would relocate the extraction and every member would
        # then land "inside" the relocated root.
        plugin_dir = contained_plugin_dir(plugin_root, manifest.get("name"))
        plugin_id = plugin_dir.name
        # Enumerated before the plugin dir even exists: an archive carrying an unsigned member is
        # refused whole, so a refused reinstall leaves the working install it would replace intact.
        undeclared = undeclared_members(zf.namelist(), manifest.get("files", []))
        if undeclared:
            raise IntegrityError(plugin_id, UNDECLARED_MEMBER, undeclared)
        plugin_dir.mkdir(parents=True, exist_ok=True)
        members = [name for name in zf.namelist() if not is_doc_member(name)]
        _extract_members(zf, plugin_dir, plugin_id, members)
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
