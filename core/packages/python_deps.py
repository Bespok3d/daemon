"""Plugin Python deps (ADR-0036): provision a per-plugin venv or symlink baked packages into the
system site-packages, then tear them down. CI bakes the deps into the .b3, so no pip runs on the
printer.

This module owns the dep POLICY and the IO orchestration: which file a plugin declared, version
coexistence across plugins that share the system interpreter, and the subprocess/symlink actions.
The pure path/name builders live in core/python_env.py; the generic symlink mechanics (placing a
link, finding its owner, testing where it points) live in core/packages/placement.py.

A plugin declares its deps as a plain file, never a manifest field, and the two are mutually
exclusive: requirements.txt -> a per-plugin venv for the plugin's own service;
klipper_requirements.txt -> baked packages symlinked into the system site-packages so Klipper or
Moonraker can import them.
"""

import shutil
import subprocess
from pathlib import Path

from .. import python_env
from ..results import MAX_OUTPUT_BYTES as _MAX_OUTPUT_BYTES
from ..results import item as _item
from ..results import phase as _phase
from .placement import points_into, replace_with_symlink, symlink_owner

_REQUIREMENTS_FILE = "requirements.txt"
_KLIPPER_REQUIREMENTS_FILE = "klipper_requirements.txt"


def _run_python_command(command: list[str], label: str) -> dict:
    result = subprocess.run(command, capture_output=True, check=False)
    raw = (result.stdout + result.stderr).decode(errors="replace")
    output = raw[:_MAX_OUTPUT_BYTES] + ("…" if len(raw) > _MAX_OUTPUT_BYTES else "")
    return _item(label, ok=result.returncode == 0, output=output.strip())


def reject_conflicting_dep_files(plugin_dir: Path) -> None:
    if (plugin_dir / _REQUIREMENTS_FILE).is_file() and (plugin_dir / _KLIPPER_REQUIREMENTS_FILE).is_file():  # noqa: E501
        raise ValueError(
            "a plugin ships requirements.txt OR klipper_requirements.txt, not both: the first goes "
            "in the plugin's own venv, the second into the system Python for Klipper/Moonraker"
        )


def reject_unbaked_deps(plugin_dir: Path) -> None:
    """A shipped requirements file must come with its baked artifacts (CI bakes them; no pip runs on
    the printer). An unbaked declaration is a broken build: fail loudly here instead of provisioning
    nothing and letting the dependent component fail to import at runtime."""
    declarations = [
        (_REQUIREMENTS_FILE, python_env.plugin_wheels_dir(plugin_dir)),
        (_KLIPPER_REQUIREMENTS_FILE, python_env.baked_site_packages_dir(plugin_dir)),
    ]
    for declaration, baked in declarations:
        if (plugin_dir / declaration).is_file() and not (baked.is_dir() and any(baked.iterdir())):
            raise ValueError(
                f"{declaration} is present but nothing was baked into {baked.relative_to(plugin_dir)}/; "  # noqa: E501
                "rebuild so the deps ship with it (CI bakes them; the printer never pips)"
            )


def _provision_venv(plugin_dir: Path, vars: dict[str, str]) -> dict | None:
    """Per-plugin venv from requirements.txt, installed offline from the baked wheels. None if absent."""  # noqa: E501
    if not (plugin_dir / _REQUIREMENTS_FILE).is_file():
        return None
    venv_path = python_env.plugin_venv_path(vars["BESPOK3D"], plugin_dir.name)
    items: list[dict] = []
    if not venv_path.exists():
        items.append(_run_python_command(python_env.venv_create_command(venv_path), f"create venv {venv_path.name}"))  # noqa: E501
    wheels = sorted(python_env.plugin_wheels_dir(plugin_dir).glob("*.whl"))
    install = python_env.requirements_install_command(venv_path, wheels)
    items.append(_run_python_command(install, "install requirements (offline)"))
    return _phase("python", "Python environment", items)


def _is_importable_entry(entry: Path) -> bool:
    if entry.name in ("bin", "__pycache__") or entry.name.endswith((".dist-info", ".egg-info")):
        return False
    return entry.is_dir() or entry.suffix == ".py"


def baked_top_level_names(plugin_dir: Path) -> list[str]:
    baked = python_env.baked_site_packages_dir(plugin_dir)
    if not baked.is_dir():
        return []
    return sorted(entry.name for entry in baked.iterdir() if _is_importable_entry(entry))


def _already_importable(module: str) -> bool:
    """True if the base interpreter already provides the module: never shadow a system package."""
    probe = f"import importlib.util,sys; sys.exit(0 if importlib.util.find_spec({module!r}) else 1)"
    result = subprocess.run(["python3", "-c", probe], capture_output=True, check=False)
    return result.returncode == 0


def _baked_version(baked: Path, name: str) -> str:
    module = python_env.import_name(name).lower()
    if not baked.is_dir():
        return ""
    for info in baked.iterdir():
        if info.name.endswith(".dist-info") and info.name.lower().startswith(module + "-"):
            return info.name[len(module) + 1:-len(".dist-info")]
    return ""


def _link_conflict(plugin_root: Path, label: str, owner: str, plugin_dir: Path, name: str) -> dict:
    ours = _baked_version(python_env.baked_site_packages_dir(plugin_dir), name)
    theirs = _baked_version(python_env.baked_site_packages_dir(plugin_root / owner), name)
    if ours and theirs and ours == theirs:
        return _item(f"{label}: already provided by {owner} at {ours}", ok=True)
    return _item(
        f"{label}: refused, {owner} already provides {name} at a different version "
        f"({theirs or 'unknown'} vs {ours or 'unknown'}); one interpreter holds one version",
        ok=False,
    )


def _site_link_precheck(plugin_root: Path, plugin_dir: Path, site_pkgs: Path, name: str) -> dict | None:  # noqa: E501
    """A terminal item (refusal, or a same-version no-op) if we must not link, else None to link."""
    module = python_env.import_name(name)
    if _already_importable(module):
        return _item(f"link {name}: refused, the base Python already provides {module!r}", ok=False)
    owner = symlink_owner(site_pkgs / name, plugin_root)
    if owner is not None and owner != plugin_dir.name:
        return _link_conflict(plugin_root, f"link {name}", owner, plugin_dir, name)
    destination = site_pkgs / name
    if destination.exists() and not destination.is_symlink():
        return _item(f"link {name}: refused, a real file already occupies {destination}", ok=False)
    return None


def _link_one_site_package(plugin_root: Path, plugin_dir: Path, site_pkgs: Path, name: str) -> dict:
    terminal = _site_link_precheck(plugin_root, plugin_dir, site_pkgs, name)
    if terminal is not None:
        return terminal
    try:
        replace_with_symlink(python_env.baked_site_packages_dir(plugin_dir) / name, site_pkgs / name)  # noqa: E501
    except Exception as exc:
        return _item(f"link {name}: {exc}", ok=False)
    return _item(f"link {name}", ok=True)


def _link_site_packages(plugin_root: Path, plugin_dir: Path, vars: dict[str, str]) -> dict | None:
    """Symlink baked packages into the system site-packages for a Klipper/Moonraker extra. None if absent."""  # noqa: E501
    if not (plugin_dir / _KLIPPER_REQUIREMENTS_FILE).is_file():
        return None
    site_pkgs = python_env.system_site_packages(vars)
    if site_pkgs is None:
        return _phase("site_packages", "System Python links", [_item("no system site-packages on this host; skipped", ok=True)])  # noqa: E501
    site_pkgs.mkdir(parents=True, exist_ok=True)
    items = [_link_one_site_package(plugin_root, plugin_dir, site_pkgs, name) for name in baked_top_level_names(plugin_dir)]  # noqa: E501
    return _phase("site_packages", "System Python links", items)


def provision_deps_phases(plugin_root: Path, plugin_dir: Path, vars: dict[str, str]) -> list[dict]:
    """The venv phase and the site-packages-link phase, whichever applies (mutually exclusive)."""
    return [phase for phase in (_provision_venv(plugin_dir, vars), _link_site_packages(plugin_root, plugin_dir, vars)) if phase is not None]  # noqa: E501


def remove_plugin_site_links(plugin_dir: Path, vars: dict[str, str]) -> list[str]:
    """Remove the system site-packages symlinks that point into this plugin's baked deps."""
    site_pkgs = python_env.system_site_packages(vars)
    if site_pkgs is None or not site_pkgs.is_dir():
        return []
    baked = python_env.baked_site_packages_dir(plugin_dir)
    removed: list[str] = []
    for entry in sorted(site_pkgs.iterdir()):
        if entry.is_symlink() and points_into(entry, baked):
            entry.unlink()
            removed.append(entry.name)
    return removed


def remove_plugin_venv(plugin_id: str, vars: dict[str, str]) -> None:
    bespok3d_root = vars.get("BESPOK3D", "")
    if bespok3d_root:
        shutil.rmtree(python_env.plugin_venv_path(bespok3d_root, plugin_id), ignore_errors=True)
