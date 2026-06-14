"""Provision a plugin's private Python environment from its `requirements.txt`.

ADR-0036: a plugin that runs its own Python service declares its dependencies in a plain
`requirements.txt`. The daemon builds a per-plugin venv at `$BESPOK3D/venv-plugins/<id>`, mirroring
the daemon's own venv, and NEVER installs into the system, Klipper, or Moonraker interpreters. The
deps are baked into the `.b3` by CI as wheels under `files/wheels/`, so the install is fully offline
and no pip ever reaches PyPI on the printer.

A plugin whose dependency must instead be importable by Klipper/Moonraker's own interpreter ships a
`klipper_requirements.txt` and the daemon symlinks the baked packages into the system site-packages
(the symlinking IO lives in `core/packages/python_deps.py`); the two files are mutually exclusive.

The path derivation, name derivation, and pip command-building here are pure; `core/packages` owns
the subprocess and symlink boundaries that act on them.
"""
from pathlib import Path

PLUGIN_VENV_DIRNAME = "venv-plugins"
PLUGIN_VENV_VAR = "PLUGIN_VENV"
_WHEELS_SUBDIR = "files/wheels"
_SITE_PACKAGES_SUBDIR = "files/site-packages"
_SITE_PACKAGES_VAR = "PYTHON_SITE_PACKAGES"


def plugin_venv_path(bespok3d_root: str, plugin_id: str) -> Path:
    return Path(bespok3d_root) / PLUGIN_VENV_DIRNAME / plugin_id


def venv_create_command(venv_path: Path) -> list[str]:
    return ["python3", "-m", "venv", str(venv_path)]


def plugin_wheels_dir(plugin_dir: Path) -> Path:
    return plugin_dir / _WHEELS_SUBDIR


def baked_site_packages_dir(plugin_dir: Path) -> Path:
    return plugin_dir / _SITE_PACKAGES_SUBDIR


def system_site_packages(vars: dict[str, str]) -> Path | None:
    """Where a Klipper/Moonraker extra's deps get linked, or None when the host declares no path."""
    target = vars.get(_SITE_PACKAGES_VAR)
    return Path(target) if target else None


def import_name(entry_name: str) -> str:
    """The importable module name of a baked top-level entry (a package dir or a single `.py`)."""
    return entry_name[:-3] if entry_name.endswith(".py") else entry_name


def requirements_install_command(venv_path: Path, wheel_files: list[Path]) -> list[str]:
    """Install the baked wheels directly, with no resolver: `--no-deps` + the explicit wheel files.
    The baked set IS the complete closure CI resolved with `pip download`, so there is nothing to
    resolve on the printer. Passing `-r requirements.txt` with version ranges instead made pip's
    offline resolver backtrack ("looking at multiple versions of...") and fail; this cannot."""
    return [
        str(venv_path / "bin" / "pip"), "install", "--no-index", "--no-deps",
        *[str(wheel) for wheel in wheel_files],
    ]
