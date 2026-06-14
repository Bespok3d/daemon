"""Provision a plugin's private Python environment from its `requirements.txt`.

ADR-0036: a plugin that runs its own Python service declares its dependencies in a plain
`requirements.txt`. The daemon builds a per-plugin venv at `$BESPOK3D/venv-plugins/<id>`, mirroring
the daemon's own venv, and NEVER installs into the system, Klipper, or Moonraker interpreters. The
deps are baked into the `.b3` by CI as wheels under `files/wheels/`, so the install is fully offline
and no pip ever reaches PyPI on the printer.

A plugin whose dependency must instead be importable by Klipper/Moonraker's own interpreter ships a
`klipper_requirements.txt` and the daemon symlinks the baked packages into the system site-packages
(handled in packages.py); the two files are mutually exclusive.

The path derivation and pip command-building here are pure; `packages.py` owns the subprocess
boundary that runs the commands.
"""
from pathlib import Path

PLUGIN_VENV_DIRNAME = "venv-plugins"
PLUGIN_VENV_VAR = "PLUGIN_VENV"
_WHEELS_SUBDIR = "files/wheels"


def plugin_venv_path(bespok3d_root: str, plugin_id: str) -> Path:
    return Path(bespok3d_root) / PLUGIN_VENV_DIRNAME / plugin_id


def venv_create_command(venv_path: Path) -> list[str]:
    return ["python3", "-m", "venv", str(venv_path)]


def plugin_wheels_dir(plugin_dir: Path) -> Path:
    return plugin_dir / _WHEELS_SUBDIR


def requirements_install_command(venv_path: Path, wheel_files: list[Path]) -> list[str]:
    """Install the baked wheels directly, with no resolver: `--no-deps` + the explicit wheel files.
    The baked set IS the complete closure CI resolved with `pip download`, so there is nothing to
    resolve on the printer. Passing `-r requirements.txt` with version ranges instead made pip's
    offline resolver backtrack ("looking at multiple versions of...") and fail; this cannot."""
    return [
        str(venv_path / "bin" / "pip"), "install", "--no-index", "--no-deps",
        *[str(wheel) for wheel in wheel_files],
    ]
