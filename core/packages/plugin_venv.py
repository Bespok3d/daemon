# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The per-plugin venv side of ADR-0036: build one at `$BESPOK3D/venv-plugins/<id>` from the wheels
CI baked into the package, and tear it down again. The other dep mode (baked packages symlinked into
the system site-packages for Klipper/Moonraker) lives in `python_deps.py`, which owns the policy
that picks between them; the pure path and command builders live in `core/python_env.py`.
"""

import shutil
import subprocess
from pathlib import Path

from .. import python_env
from ..results import MAX_OUTPUT_BYTES, item, phase
from .plugin_dir import contained_plugin_dir
from .venv_health import broken_wheels, unrecorded_dist_infos

_INSTALL_LABEL = "install requirements (offline)"
_REPAIR_LABEL = "repair broken requirements (offline)"


def _run_python_command(command: list[str], label: str) -> dict:
    result = subprocess.run(command, capture_output=True, check=False)
    raw = (result.stdout + result.stderr).decode(errors="replace")
    output = raw[:MAX_OUTPUT_BYTES] + ("…" if len(raw) > MAX_OUTPUT_BYTES else "")
    return item(label, ok=result.returncode == 0, output=output.strip())


def provision_venv_phase(plugin_dir: Path, vars: dict[str, str]) -> dict | None:
    """Per-plugin venv from requirements.txt, installed offline from the baked wheels. None if absent."""  # noqa: E501
    if not (plugin_dir / python_env.REQUIREMENTS_FILE).is_file():
        return None
    venv_path = python_env.plugin_venv_path(vars["BESPOK3D"], plugin_dir.name)
    items: list[dict] = []
    if not venv_path.exists():
        items.append(_run_python_command(python_env.venv_create_command(venv_path), f"create venv {venv_path.name}"))  # noqa: E501
    wheels = sorted(python_env.plugin_wheels_dir(plugin_dir).glob("*.whl"))
    items.append(_install_item(venv_path, wheels))
    if items[-1]["ok"]:
        items.extend(_repair_items(venv_path, wheels))
    return phase("python", "Python environment", items)


def _install_item(venv_path: Path, wheels: list[Path]) -> dict:
    try:
        _drop_unrecorded_dist_infos(venv_path, wheels)
    except OSError as failure:
        return item(_INSTALL_LABEL, ok=False, output=f"{type(failure).__name__}: {failure}")
    install = python_env.requirements_install_command(venv_path, wheels)
    return _run_python_command(install, _INSTALL_LABEL)


def _drop_unrecorded_dist_infos(venv_path: Path, wheels: list[Path]) -> None:
    """pip uninstalls a distribution by its RECORD before it installs over it and fails without
    one; with the dist-info gone it installs the wheel as new, writing over the old files."""
    for dist_info in unrecorded_dist_infos(venv_path, wheels):
        _remove_dist_info(dist_info)


def _remove_dist_info(dist_info: Path) -> None:
    """rmtree refuses a symlink, and the link is the entry pip reads, so the link is removed."""
    if dist_info.is_symlink():
        dist_info.unlink()
        return
    shutil.rmtree(dist_info)


def _repair_items(venv_path: Path, wheels: list[Path]) -> list[dict]:
    """The reinstall of the wheels whose installed files no longer match their RECORD, if any:
    the install above skipped them as already there."""
    broken = broken_wheels(venv_path, wheels)
    if not broken:
        return []
    return [_run_python_command(python_env.wheel_repair_command(venv_path, broken), _REPAIR_LABEL)]


def remove_plugin_venv(plugin_id: str, vars: dict[str, str]) -> None:
    """Delete the plugin's venv. The id is contained first: this deletes as root, and an id naming
    anything but its own directory under the venv root would take the rest of the tree with it."""
    bespok3d_root = vars.get("BESPOK3D", "")
    if not bespok3d_root:
        return
    venv_root = python_env.plugin_venv_root(bespok3d_root)
    shutil.rmtree(contained_plugin_dir(venv_root, plugin_id), ignore_errors=True)
