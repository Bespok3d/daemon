"""
Package operations: install, uninstall.

A .b3 package is a zip containing manifest.json plus the plugin file tree.
Install is manifest-driven: dirs, symlinks, and unified-diff patches.
Signature verification is deferred until packages are signed.
"""

import json
import os
import re
import shutil
import subprocess
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jinni.loader import get_jinni

from . import python_env
from .intent import (
    RESTART_HOOKS,
    SERVICE_SCRIPT_DIR,
    _is_service_action,
    _restarts_klipper,
    _restarts_lmd,
    _restarts_moonraker,
    normalize_install,
    service_script_name,
)
from .klippy_uds import query_print_state as _query_print_state
from .results import MAX_OUTPUT_BYTES as _MAX_OUTPUT_BYTES
from .results import item as _item
from .results import phase as _phase
from .safety import (
    Decision,
    FailureEvidence,
    OperationContext,
    OperationKind,
    decide,
    is_healthy,
)
from .safety.attribution import AttributionIndex, Placement
from .safety.attribution import build_index as build_attribution_index
from .safety.health import MQTT_PORT as _MQTT_PORT
from .safety.health import config_link_dirs as _config_link_dirs  # noqa: F401  re-export for tests
from .safety.health import klipper_healthy as _klipper_healthy  # noqa: F401  re-export for tests
from .safety.health import klippy_socket_path as _klippy_socket_path
from .safety.health import (
    moonraker_healthy as _moonraker_healthy,  # noqa: F401  re-export for tests
)
from .safety.health import port_listening as _port_listening
from .safety.health import probe_moonraker as _probe_moonraker
from .safety.health import (
    prune_dead_config_links as _prune_dead_config_links,  # noqa: F401  re-export
)
from .safety.health import (
    restart_moonraker as _restart_moonraker,  # noqa: F401  re-export for tests
)
from .safety.health import run_restart_batch as _run_restart_batch
from .safety.health import wait_for_klipper_item as _wait_for_klipper_item  # noqa: F401  re-export
from .safety.health import (
    wait_for_moonraker_item as _wait_for_moonraker_item,  # noqa: F401  re-export
)
from .safety.logs import format_tails as _format_tails
from .safety.logs import read_log_tail as _read_log_tail
from .shell import run_one_command as _run_one_start_command
from .shell import start_env as _start_env

_DATA_ROOT = Path(os.environ.get("BESPOK3D_DATA_ROOT", "/userdata/bespok3d"))
PLUGIN_ROOT = _DATA_ROOT / "usr/local/plugins"

# A plugin declares its Python deps as a plain file (ADR-0036), never a manifest field. The two are
# mutually exclusive: requirements.txt -> a per-plugin venv for the plugin's own service;
# klipper_requirements.txt -> baked packages symlinked into the system site-packages so Klipper or
# Moonraker can import them. CI bakes the deps into the .b3 so no pip runs on the printer.
_REQUIREMENTS_FILE = "requirements.txt"
_KLIPPER_REQUIREMENTS_FILE = "klipper_requirements.txt"
_BAKED_SITE_PACKAGES = "files/site-packages"
_BAKED_WHEELS = "files/wheels"
_SITE_PACKAGES_VAR = "PYTHON_SITE_PACKAGES"

# The comma is allowed for list-valued config (e.g. NOTIFY_EVENTS="complete,error,cancelled"). It is
# safe in the shell-interpolated `install.start` commands: a bare comma is not a metacharacter, and
# brace expansion (its only special use) needs `{`/`}`, which this allowlist already blocks.
_SAFE_VAR_RE = re.compile(r'^[A-Za-z0-9 .,\-:/_@]+$')
_SAFE_VAR_ALLOWED = "letters, numbers, spaces, and . , - : / _ @"


class DependentsError(Exception):
    """Uninstall was refused because installed plugins still depend on the target."""

    def __init__(self, plugin_id: str, dependents: list[str]) -> None:
        self.plugin_id = plugin_id
        self.dependents = dependents
        super().__init__(f"{plugin_id} is required by: {', '.join(dependents)}")


class ConflictError(Exception):
    """Install was refused because the package conflicts with an installed plugin."""

    def __init__(self, plugin_id: str, conflicts: list[str]) -> None:
        self.plugin_id = plugin_id
        self.conflicts = conflicts
        super().__init__(f"{plugin_id} conflicts with installed: {', '.join(conflicts)}")


def validate_user_vars(user_vars: dict[str, str]) -> None:
    for key, value in user_vars.items():
        if not _SAFE_VAR_RE.match(value):
            raise ValueError(f"Variable {key!r} allows only {_SAFE_VAR_ALLOWED}. Got: {value!r}")


def _expand(template: str, vars: dict[str, str]) -> str:
    expanded = template
    for key in sorted(vars, key=len, reverse=True):
        expanded = expanded.replace(f"${key}", vars[key])
    return expanded


def _apply_modes(plugin_dir: Path, files: list[dict]) -> dict:
    items: list[dict] = []
    for entry in files:
        path = plugin_dir / entry["path"]
        if path.exists():
            try:
                path.chmod(int(entry["mode"], 8))
                items.append(_item(f"{entry['path']} → {entry['mode']}", ok=True))
            except Exception as exc:
                items.append(_item(f"{entry['path']}: {exc}", ok=False))
    return _phase("modes", "File modes", items)


def _create_dirs(dirs: list[str], vars: dict[str, str]) -> dict:
    items: list[dict] = []
    for directory in dirs:
        expanded = _expand(directory, vars)
        try:
            Path(expanded).mkdir(parents=True, exist_ok=True)
            items.append(_item(expanded, ok=True))
        except Exception as exc:
            items.append(_item(f"{expanded}: {exc}", ok=False))
    return _phase("dirs", "Directories", items)


_SYMLINK_ORIG_DIR = "symlink_orig"


def _symlink_backup_path(plugin_dir: Path, destination: Path) -> Path:
    key = destination.as_posix().strip("/").replace("/", "__") or "root"
    return plugin_dir / _SYMLINK_ORIG_DIR / key


def _clear_existing_destination(destination: Path) -> None:
    if destination.is_symlink():
        destination.unlink()
        return
    if destination.is_dir():
        shutil.rmtree(destination)
        return
    if destination.exists():
        destination.unlink()


def _is_stock_original(path: Path) -> bool:
    """A real dir/file (the stock original worth preserving), not a symlink or overlay whiteout."""
    return (path.is_dir() or path.is_file()) and not path.is_symlink()


def _displace_existing_destination(destination: Path, backup: Path) -> None:
    """Make room for our symlink while preserving any stock original so teardown can restore it.
    A real dir/file is MOVED to the plugin-owned backup the first time only (pristine original
    wins over a regenerated copy); a symlink or overlay whiteout is just cleared, never saved."""
    if not _is_stock_original(destination) or backup.exists():
        _clear_existing_destination(destination)
        return
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(destination), str(backup))


def _replace_with_symlink(source: Path, destination: Path, backup: Path | None = None) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if backup is None:
        _clear_existing_destination(destination)
    else:
        _displace_existing_destination(destination, backup)
    destination.symlink_to(source)


def _create_one_symlink(link: dict, plugin_dir: Path, vars: dict[str, str]) -> dict:
    source = (plugin_dir / link["from"]).resolve()
    destination = Path(_expand(link["to"], vars))
    backup = _symlink_backup_path(plugin_dir, destination)
    label = f"{link['from']} → {destination}"
    try:
        _replace_with_symlink(source, destination, backup)
    except Exception as exc:
        return _item(f"{label}: {exc}", ok=False)
    return _item(label, ok=True)


def _create_symlinks(symlinks: list[dict], plugin_dir: Path, vars: dict[str, str]) -> dict:
    items = [_create_one_symlink(link, plugin_dir, vars) for link in symlinks]
    return _phase("symlinks", "Symlinks", items)


_PRINTING_STATES = ("printing", "paused")


def _print_state_via_moonraker() -> str:
    """Fallback when Klipper's API socket is unavailable. Returns "" on any failure (including a 401
    under force_logins), which reads as idle: the auth-immune Klipper socket is the main source."""
    try:
        url = "http://localhost:7125/printer/objects/query?print_stats"
        with urllib.request.urlopen(url, timeout=3) as resp:
            payload = json.loads(resp.read().decode(errors="replace"))
    except Exception:
        return ""
    return str(payload.get("result", {}).get("status", {}).get("print_stats", {}).get("state", ""))


def _print_active() -> tuple[bool, str]:
    """Return (is_active, state). Reads Klipper's print_stats over its API socket (no auth, so it
    works even when the moonraker-auth plugin forces logins); falls back to Moonraker HTTP when the
    socket is unavailable. An idle / unreadable result is treated as not-printing."""
    socket_path = _klippy_socket_path()
    state = _query_print_state(socket_path) if socket_path else None
    if state is None:
        state = _print_state_via_moonraker()
    return state in _PRINTING_STATES, state


def _manifest_restarts_services(manifest: dict) -> bool:
    ops = normalize_install(manifest.get("install", {}))
    start_cmds = ops["start"]
    if any(_restarts_klipper(cmd) or _restarts_moonraker(cmd) for cmd in start_cmds):
        return True
    # A plugin that bounces the display service (lmd) is detectable two ways: the generic
    # `restart: ["lmd"]` hook lands an `lmdctl` command in `start`, and a display-owning plugin
    # like camera-hw-accel (whose start runs its own init script with no literal "lmd") declares
    # `lmdctl restart` in its teardown `stop`. Either marks it as display-touching.
    display_cmds = [*start_cmds, *ops["stops"], *manifest.get("stop", [])]
    return any(_restarts_lmd(cmd) for cmd in display_cmds)


def _guard_no_print(action: str) -> None:
    """Refuse a system-wide plugin op (deactivate/teardown/recover) while printing or paused.

    These bounce services across all plugins, so the check is unconditional: a LIVE Moonraker
    query at the moment of the op, never a cached/periodic value.
    """
    active, state = _print_active()
    if active:
        raise ValueError(
            f"Cannot {action} while a print is {state}: it restarts printer services, which "
            "would interrupt the print. Try again when the printer is idle."
        )


def _guard_no_print_during_restart(manifest: dict, action: str = "install") -> None:
    """Refuse an op that would bounce Klipper, Moonraker, or the display while printing/paused."""
    if not _manifest_restarts_services(manifest):
        return
    active, state = _print_active()
    if not active:
        return
    raise ValueError(
        f"Cannot {action} {manifest.get('name', 'this plugin')} while a print is {state}: "
        "it restarts Klipper, Moonraker, or the display service, which would interrupt the "
        "print. Try again when the printer is idle."
    )


def _run_plugin_start_commands(cmds: list[str], vars: dict[str, str]) -> tuple[dict, list[str]]:
    """Run a plugin's plugin-specific start commands; defer Klipper/Moonraker restarts.

    Returns the start phase plus the deferred service-restart commands so the caller can
    run them once at the end of a batch instead of bouncing Klipper/Moonraker per plugin.
    """
    env = _start_env()
    expanded_cmds = [_expand(cmd, vars) for cmd in cmds]
    immediate = [cmd for cmd in expanded_cmds if not _is_service_action(cmd)]
    deferred = [cmd for cmd in expanded_cmds if _is_service_action(cmd)]
    items = [_run_one_start_command(cmd, env) for cmd in immediate]
    return _phase("start", "Start commands", items), deferred


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


def _apply_patches(patches: list[dict], plugin_dir: Path, vars: dict[str, str]) -> dict:
    items: list[dict] = []
    orig_dir = plugin_dir / "patches_orig"
    orig_dir.mkdir(parents=True, exist_ok=True)
    for patch_def in patches:
        target = Path(_expand(patch_def["file"], vars))
        patch_file = plugin_dir / patch_def["patch"]
        label = f"patch {target.name}"
        if not target.exists():
            items.append(_item(label, ok=False, output="target file not found"))
            continue
        ok, raw = _apply_one_patch(target, patch_file, orig_dir)
        output = raw[:_MAX_OUTPUT_BYTES] + ("…" if len(raw) > _MAX_OUTPUT_BYTES else "")
        items.append(_item(label, ok=ok, output=output.strip()))
    return _phase("patches", "Patches", items)


_USER_VARS_FILE = "user_vars.json"


def _persist_user_vars(plugin_dir: Path, user_vars: dict[str, str]) -> None:
    if not user_vars:
        return
    (plugin_dir / _USER_VARS_FILE).write_text(json.dumps(user_vars))


def _load_user_vars(plugin_dir: Path) -> dict[str, str]:
    path = plugin_dir / _USER_VARS_FILE
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _render_one_template(template_def: dict, plugin_dir: Path, vars: dict[str, str]) -> dict:
    template_rel = template_def["from"]
    template_to = template_def["to"]
    label = f"{template_rel} → {template_to}"
    if template_to.startswith("/") or ".." in Path(template_to).parts:
        return _item(f"{label}: template 'to' must be relative and within the plugin dir", ok=False)
    template_path = plugin_dir / template_rel
    target_path = plugin_dir / template_to
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        body = template_path.read_text()
        target_path.write_text(_expand(body, vars))
    except Exception as exc:
        return _item(f"{label}: {exc}", ok=False)
    return _item(label, ok=True)


def _render_templates(templates: list[dict], plugin_dir: Path, vars: dict[str, str]) -> dict:
    items = [_render_one_template(template_def, plugin_dir, vars) for template_def in templates]
    return _phase("templates", "Templates", items)


def _expand_service(service: dict, vars: dict[str, str]) -> dict:
    return {
        **service,
        "command": _expand(service["command"], vars),
        "args": [_expand(arg, vars) for arg in service.get("args", [])],
    }


def _write_one_service_script(service: dict, plugin_dir: Path, vars: dict[str, str], jinni: Any) -> dict:  # noqa: E501
    script_name = service_script_name(service)
    if "managed-service" not in jinni.capability_flags():
        return _item(f"{script_name}: managed services not supported on this printer", ok=False)
    target = plugin_dir / SERVICE_SCRIPT_DIR / script_name
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(jinni.render_service_script(_expand_service(service, vars), vars))
        target.chmod(0o755)
    except Exception as exc:
        return _item(f"{script_name}: {exc}", ok=False)
    return _item(script_name, ok=True)


def _generate_service_scripts(services: list[dict], plugin_dir: Path, vars: dict[str, str]) -> dict:
    jinni = get_jinni()
    items = [_write_one_service_script(service, plugin_dir, vars, jinni) for service in services]
    return _phase("services", "Services", items)


def _run_python_command(command: list[str], label: str) -> dict:
    result = subprocess.run(command, capture_output=True, check=False)
    raw = (result.stdout + result.stderr).decode(errors="replace")
    output = raw[:_MAX_OUTPUT_BYTES] + ("…" if len(raw) > _MAX_OUTPUT_BYTES else "")
    return _item(label, ok=result.returncode == 0, output=output.strip())


def _reject_conflicting_dep_files(plugin_dir: Path) -> None:
    if (plugin_dir / _REQUIREMENTS_FILE).is_file() and (plugin_dir / _KLIPPER_REQUIREMENTS_FILE).is_file():  # noqa: E501
        raise ValueError(
            "a plugin ships requirements.txt OR klipper_requirements.txt, not both: the first goes "
            "in the plugin's own venv, the second into the system Python for Klipper/Moonraker"
        )


def _has_baked_artifacts(directory: Path) -> bool:
    return directory.is_dir() and any(directory.iterdir())


def _reject_unbaked_deps(plugin_dir: Path) -> None:
    """A shipped requirements file must come with its baked artifacts (CI bakes them; no pip runs on
    the printer). An unbaked declaration is a broken build: fail loudly here instead of provisioning
    nothing and letting the dependent component fail to import at runtime."""
    if (plugin_dir / _REQUIREMENTS_FILE).is_file() and not _has_baked_artifacts(plugin_dir / _BAKED_WHEELS):  # noqa: E501
        raise ValueError(
            "requirements.txt is present but no wheels were baked into files/wheels/; rebuild the "
            "plugin so its dependencies ship with it (CI bakes them; the printer never runs pip)"
        )
    if (plugin_dir / _KLIPPER_REQUIREMENTS_FILE).is_file() and not _has_baked_artifacts(plugin_dir / _BAKED_SITE_PACKAGES):  # noqa: E501
        raise ValueError(
            "klipper_requirements.txt is present but nothing was baked into files/site-packages/; "
            "rebuild the plugin so its deps ship with it (CI bakes them; printer never pips)"
        )


def _provision_venv(plugin_dir: Path, vars: dict[str, str]) -> dict | None:
    """Per-plugin venv from requirements.txt, installed offline from the baked wheels. None if absent."""  # noqa: E501
    requirements = plugin_dir / _REQUIREMENTS_FILE
    if not requirements.is_file():
        return None
    venv_path = python_env.plugin_venv_path(vars["BESPOK3D"], plugin_dir.name)
    items: list[dict] = []
    if not venv_path.exists():
        items.append(_run_python_command(python_env.venv_create_command(venv_path), f"create venv {venv_path.name}"))  # noqa: E501
    wheels = sorted(python_env.plugin_wheels_dir(plugin_dir).glob("*.whl"))
    install = python_env.requirements_install_command(venv_path, wheels)
    items.append(_run_python_command(install, "install requirements (offline)"))
    return _phase("python", "Python environment", items)


def _baked_site_packages(plugin_dir: Path) -> Path:
    return plugin_dir / _BAKED_SITE_PACKAGES


def _import_name(entry_name: str) -> str:
    return entry_name[:-3] if entry_name.endswith(".py") else entry_name


def _is_importable_entry(entry: Path) -> bool:
    if entry.name in ("bin", "__pycache__") or entry.name.endswith((".dist-info", ".egg-info")):
        return False
    return entry.is_dir() or entry.suffix == ".py"


def _baked_top_level_names(plugin_dir: Path) -> list[str]:
    baked = _baked_site_packages(plugin_dir)
    if not baked.is_dir():
        return []
    return sorted(entry.name for entry in baked.iterdir() if _is_importable_entry(entry))


def _system_site_packages(vars: dict[str, str]) -> Path | None:
    target = vars.get(_SITE_PACKAGES_VAR)
    return Path(target) if target else None


def _already_importable(module: str) -> bool:
    """True if the base interpreter already provides the module: never shadow a system package."""
    probe = f"import importlib.util,sys; sys.exit(0 if importlib.util.find_spec({module!r}) else 1)"
    result = subprocess.run(["python3", "-c", probe], capture_output=True, check=False)
    return result.returncode == 0


def _baked_version(baked: Path, name: str) -> str:
    module = _import_name(name).lower()
    if not baked.is_dir():
        return ""
    for info in baked.iterdir():
        if info.name.endswith(".dist-info") and info.name.lower().startswith(module + "-"):
            return info.name[len(module) + 1:-len(".dist-info")]
    return ""


def _existing_link_owner(site_pkgs: Path, name: str) -> str | None:
    link = site_pkgs / name
    if not link.is_symlink():
        return None
    try:
        relative = link.resolve().relative_to(PLUGIN_ROOT)
    except (ValueError, OSError):
        return None
    return relative.parts[0] if relative.parts else None


def _link_conflict(label: str, owner: str, plugin_dir: Path, name: str) -> dict:
    ours = _baked_version(_baked_site_packages(plugin_dir), name)
    theirs = _baked_version(_baked_site_packages(PLUGIN_ROOT / owner), name)
    if ours and theirs and ours == theirs:
        return _item(f"{label}: already provided by {owner} at {ours}", ok=True)
    return _item(
        f"{label}: refused, {owner} already provides {name} at a different version "
        f"({theirs or 'unknown'} vs {ours or 'unknown'}); one interpreter holds one version",
        ok=False,
    )


def _site_link_precheck(plugin_dir: Path, site_pkgs: Path, name: str) -> dict | None:
    """A terminal item (refusal, or a same-version no-op) if we must not link, else None to link."""
    module = _import_name(name)
    if _already_importable(module):
        return _item(f"link {name}: refused, the base Python already provides {module!r}", ok=False)
    owner = _existing_link_owner(site_pkgs, name)
    if owner is not None and owner != plugin_dir.name:
        return _link_conflict(f"link {name}", owner, plugin_dir, name)
    destination = site_pkgs / name
    if destination.exists() and not destination.is_symlink():
        return _item(f"link {name}: refused, a real file already occupies {destination}", ok=False)
    return None


def _link_one_site_package(plugin_dir: Path, site_pkgs: Path, name: str) -> dict:
    terminal = _site_link_precheck(plugin_dir, site_pkgs, name)
    if terminal is not None:
        return terminal
    try:
        _replace_with_symlink(_baked_site_packages(plugin_dir) / name, site_pkgs / name)
    except Exception as exc:
        return _item(f"link {name}: {exc}", ok=False)
    return _item(f"link {name}", ok=True)


def _link_site_packages(plugin_dir: Path, vars: dict[str, str]) -> dict | None:
    """Symlink baked packages into the system site-packages for a Klipper/Moonraker extra. None if absent."""  # noqa: E501
    if not (plugin_dir / _KLIPPER_REQUIREMENTS_FILE).is_file():
        return None
    site_pkgs = _system_site_packages(vars)
    if site_pkgs is None:
        return _phase("site_packages", "System Python links", [_item("no system site-packages on this host; skipped", ok=True)])  # noqa: E501
    site_pkgs.mkdir(parents=True, exist_ok=True)
    items = [_link_one_site_package(plugin_dir, site_pkgs, name) for name in _baked_top_level_names(plugin_dir)]  # noqa: E501
    return _phase("site_packages", "System Python links", items)


def _provision_deps_phases(plugin_dir: Path, vars: dict[str, str]) -> list[dict]:
    """The venv phase and the site-packages-link phase, whichever applies (mutually exclusive)."""
    return [phase for phase in (_provision_venv(plugin_dir, vars), _link_site_packages(plugin_dir, vars)) if phase is not None]  # noqa: E501


def _points_into(link: Path, baked: Path) -> bool:
    try:
        link.resolve().relative_to(baked.resolve())
    except (ValueError, OSError):
        return False
    return True


def _remove_plugin_site_links(plugin_dir: Path, vars: dict[str, str]) -> list[str]:
    """Remove the system site-packages symlinks that point into this plugin's baked deps."""
    site_pkgs = _system_site_packages(vars)
    if site_pkgs is None or not site_pkgs.is_dir():
        return []
    baked = _baked_site_packages(plugin_dir)
    removed: list[str] = []
    for entry in sorted(site_pkgs.iterdir()):
        if entry.is_symlink() and _points_into(entry, baked):
            entry.unlink()
            removed.append(entry.name)
    return removed


def _with_plugin_venv(vars: dict[str, str], plugin_id: str) -> dict[str, str]:
    """Expose the deterministic per-plugin venv path as $PLUGIN_VENV for service commands."""
    venv_path = python_env.plugin_venv_path(vars.get("BESPOK3D", ""), plugin_id)
    return {**vars, python_env.PLUGIN_VENV_VAR: str(venv_path)}


def ensure_lmd_control_script(jinni: Any, paths: dict[str, str]) -> None:
    """Place the jinni's hardened lmd control script at $BESPOK3D/etc/init.d/lmdctl (0755).

    Rendered into the persistent bespok3d tree (not symlinked into the redeployed daemon dir) so it
    survives a full daemon redeploy. Gated on the adapter advertising `lmd-control`, so a generic
    daemon and non-display adapters write nothing.
    """
    if "lmd-control" not in jinni.capability_flags():
        return
    target = Path(paths["BESPOK3D"]) / "etc/init.d/lmdctl"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(jinni.render_lmd_control_script(paths))
    target.chmod(0o755)


def _fix_ownership(plugin_dir: Path, runtime_user: str) -> dict:
    items: list[dict] = []
    chmod_result = subprocess.run(
        ["chmod", "-R", "755", str(plugin_dir)], capture_output=True, check=False,
    )
    items.append(_item(f"chmod -R 755 {plugin_dir.name}", ok=chmod_result.returncode == 0))
    if runtime_user:
        chown_result = subprocess.run(
            ["chown", "-R", f"{runtime_user}:{runtime_user}", str(plugin_dir)],
            capture_output=True,
            check=False,
        )
        items.append(_item(
            f"chown -R {runtime_user} {plugin_dir.name}",
            ok=chown_result.returncode == 0,
        ))
    return _phase("ownership", "Permissions", items)


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


def _unpack_package(package_path: Path) -> tuple[dict, Path, int]:
    with zipfile.ZipFile(package_path) as zf:
        if "manifest.json" not in zf.namelist():
            raise ValueError("missing manifest.json")
        manifest = json.loads(zf.read("manifest.json"))
        _guard_no_print_during_restart(manifest)
        plugin_dir = PLUGIN_ROOT / manifest["name"]
        plugin_dir.mkdir(parents=True, exist_ok=True)
        # doc/ is catalog documentation, never deployed: printer space is at a premium.
        members = [name for name in zf.namelist() if not _is_doc_member(name)]
        _extract_members(zf, plugin_dir, members)
        file_count = len(members)
    shutil.rmtree(plugin_dir / "doc", ignore_errors=True)
    _reject_conflicting_dep_files(plugin_dir)
    _reject_unbaked_deps(plugin_dir)
    return manifest, plugin_dir, file_count


PhaseListener = Callable[[dict], None]


def _noop_phase(_phase: dict) -> None:
    return None


def _emit(phase: dict, notify: PhaseListener) -> dict:
    """Append-and-announce: report a phase the moment it finishes so a watcher (the install-progress
    feed) sees it live, while still returning it for the final install log."""
    notify(phase)
    return phase


def _install_apply_phases(plugin_dir: Path, manifest: dict, full_vars: dict[str, str], on_phase: PhaseListener | None = None) -> list[dict]:  # noqa: E501
    """Run a fresh install's phases, announcing each as it finishes. A core-service restart goes
    through the auto-fix safety net, so a plugin that breaks Klipper/Moonraker is deactivated and
    the printer stays usable (the protection recover/OTA already had)."""
    raw_inst = manifest.get("install", {})
    inst = normalize_install(raw_inst)
    notify = on_phase or _noop_phase
    phases = [
        _emit(_apply_modes(plugin_dir, manifest.get("files", [])), notify),
        _emit(_create_dirs(inst["dirs"], full_vars), notify),
        _emit(_render_templates(inst["templates"], plugin_dir, full_vars), notify),
        _emit(_generate_service_scripts(raw_inst.get("service", []), plugin_dir, full_vars), notify),  # noqa: E501
        _emit(_create_symlinks(inst["symlinks"], plugin_dir, full_vars), notify),
        _emit(_apply_patches(inst["patches"], plugin_dir, full_vars), notify),
        _emit(_fix_ownership(plugin_dir, full_vars.get("RUNTIME_USER", "")), notify),
    ]
    phases.extend(_emit(phase, notify) for phase in _provision_deps_phases(plugin_dir, full_vars))
    start_phase, deferred = _run_plugin_start_commands(inst["start"], full_vars)
    phases.append(_emit(start_phase, notify))
    phases.extend(_emit(phase, notify) for phase in _restart_phases(deferred, full_vars, _op_context(OperationKind.INSTALL, manifest)))  # noqa: E501
    return phases


def install(
    package_path: Path,
    vars: dict[str, str],
    user_vars: dict[str, str] | None = None,
    on_phase: PhaseListener | None = None,
) -> tuple[str, list[dict]]:
    manifest, plugin_dir, file_count = _unpack_package(package_path)
    plugin_id: str = manifest["name"]

    conflicts = installed_conflicts(plugin_id, manifest)
    if conflicts:
        shutil.rmtree(plugin_dir, ignore_errors=True)
        raise ConflictError(plugin_id, conflicts)

    notify = on_phase or _noop_phase
    extract_items = [_item(f"Extracted {file_count} files", ok=True)]
    log: list[dict] = [_emit(_phase("extract", "Unpack", extract_items), notify)]

    _persist_user_vars(plugin_dir, user_vars or {})
    full_vars = _with_plugin_venv(vars, plugin_id)
    log.extend(_install_apply_phases(plugin_dir, manifest, full_vars, on_phase))
    if all(phase["ok"] for phase in log):
        _clear_failure_markers(plugin_dir)

    return plugin_id, log


def reconfigure(
    plugin_id: str,
    vars: dict[str, str],
    user_vars: dict[str, str],
) -> tuple[str, list[dict]]:
    """Re-render a plugin's config templates from new values and restart its services.

    Lighter than a reinstall: files, symlinks, and patches are left untouched; only the
    rendered config files change. Relies on installs being idempotent.
    """
    plugin_dir = PLUGIN_ROOT / plugin_id
    manifest_path = plugin_dir / "manifest.json"
    if not manifest_path.exists():
        raise ValueError(f"plugin {plugin_id!r} is not installed")
    manifest = json.loads(manifest_path.read_text())
    _guard_no_print_during_restart(manifest)

    full_vars = _with_plugin_venv(vars, plugin_id)
    inst = normalize_install(manifest.get("install", {}))
    _persist_user_vars(plugin_dir, user_vars)
    start_phase, deferred = _run_plugin_start_commands(inst.get("start", []), full_vars)
    phases = [
        _render_templates(inst.get("templates", []), plugin_dir, full_vars),
        _fix_ownership(plugin_dir, full_vars.get("RUNTIME_USER", "")),
        start_phase,
    ]
    phases.extend(_restart_phases(deferred, full_vars, _op_context(OperationKind.RECONFIGURE, manifest)))  # noqa: E501
    return plugin_id, phases


def _run_stop_commands(cmds: list[str], vars: dict[str, str]) -> None:
    env = {**os.environ, "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}
    for cmd in cmds:
        subprocess.run(_expand(cmd, vars), shell=True, capture_output=True, check=False, env=env)


_DEACTIVATED_MARKER = "deactivated.json"
_RECOVERY_FAILURE_MARKER = "recovery_failure.json"


def _clear_failure_markers(plugin_dir: Path) -> None:
    """A plugin that re-applies cleanly is no longer failed or deactivated; drop stale markers."""
    (plugin_dir / _DEACTIVATED_MARKER).unlink(missing_ok=True)
    (plugin_dir / _RECOVERY_FAILURE_MARKER).unlink(missing_ok=True)


def _dep_capability(dep_str: str) -> str:
    return dep_str.split("@")[0]


def _provided_services(manifest: dict) -> list[str]:
    """Service names a manifest provides, in either the service-model or legacy flat form."""
    provides = manifest.get("provides", [])
    return [item["service"] if isinstance(item, dict) else item for item in provides]


def _required_services(manifest: dict) -> list[str]:
    """Service names a manifest requires, from `require: [{service}]` or legacy `depends`."""
    requires = manifest.get("require")
    if requires is not None:
        return [requirement["service"] for requirement in requires]
    legacy = [_dep_capability(dep) for dep in manifest.get("depends", [])]
    return [service for service in legacy if service != "base"]


def _installed_manifest_dirs() -> list[Path]:
    if not PLUGIN_ROOT.exists():
        return []
    return [
        plugin_dir for plugin_dir in sorted(PLUGIN_ROOT.iterdir())
        if plugin_dir.is_dir() and (plugin_dir / "manifest.json").exists()
    ]


def _manifest_at(plugin_dir: Path) -> dict:
    return json.loads((plugin_dir / "manifest.json").read_text())


def _depends_on_any(plugin_dir: Path, services: set[str]) -> bool:
    declared = set(_required_services(_manifest_at(plugin_dir)))
    return bool(declared & services)


def installed_dependents(plugin_id: str) -> list[str]:
    """Installed plugins that depend on a service the target plugin provides."""
    target_dir = PLUGIN_ROOT / plugin_id
    if not (target_dir / "manifest.json").exists():
        return []
    provided = set(_provided_services(_manifest_at(target_dir)))
    if not provided:
        return []
    others = [plugin_dir for plugin_dir in _installed_manifest_dirs() if plugin_dir != target_dir]
    return [plugin_dir.name for plugin_dir in others if _depends_on_any(plugin_dir, provided)]


def installed_conflicts(plugin_id: str, manifest: dict) -> list[str]:
    """Installed plugins that this package excludes, or that exclude this package."""
    declared = set(manifest.get("conflicts", []))
    others = [
        plugin_dir for plugin_dir in _installed_manifest_dirs()
        if plugin_dir.name != plugin_id
    ]
    clashing = {
        plugin_dir.name for plugin_dir in others
        if plugin_dir.name in declared or plugin_id in _manifest_at(plugin_dir).get("conflicts", [])
    }
    return sorted(clashing)


def _record_dep_edge(
    dependent: Path,
    dep_str: str,
    provides_map: dict[str, Path],
    in_degree: dict[Path, int],
    reverse_deps: dict[Path, list[Path]],
) -> None:
    cap = _dep_capability(dep_str)
    if cap not in provides_map or provides_map[cap] == dependent:
        return
    provider = provides_map[cap]
    in_degree[dependent] += 1
    reverse_deps[provider].append(dependent)


def _build_dep_graph(
    plugin_dirs: list[Path],
    manifests: dict[Path, dict[str, Any]],
    provides_map: dict[str, Path],
) -> tuple[dict[Path, int], dict[Path, list[Path]]]:
    in_degree: dict[Path, int] = {plugin_dir: 0 for plugin_dir in plugin_dirs}
    reverse_deps: dict[Path, list[Path]] = {plugin_dir: [] for plugin_dir in plugin_dirs}
    for plugin_dir in plugin_dirs:
        for service in _required_services(manifests[plugin_dir]):
            _record_dep_edge(plugin_dir, service, provides_map, in_degree, reverse_deps)
    return in_degree, reverse_deps


def _decrement_and_enqueue(
    dependents: list[Path],
    in_degree: dict[Path, int],
    queue: list[Path],
) -> None:
    for dependent in dependents:
        in_degree[dependent] -= 1
        if in_degree[dependent] == 0:
            queue.append(dependent)


def _topo_sort(plugin_dirs: list[Path]) -> list[Path]:
    manifests: dict[Path, dict[str, Any]] = {}
    provides_map: dict[str, Path] = {}
    for plugin_dir in plugin_dirs:
        manifest = json.loads((plugin_dir / "manifest.json").read_text())
        manifests[plugin_dir] = manifest
        for service in _provided_services(manifest):
            provides_map[service] = plugin_dir

    in_degree, reverse_deps = _build_dep_graph(plugin_dirs, manifests, provides_map)
    queue = [plugin_dir for plugin_dir in plugin_dirs if in_degree[plugin_dir] == 0]
    ordered: list[Path] = []
    while queue:
        node = queue.pop(0)
        ordered.append(node)
        _decrement_and_enqueue(reverse_deps[node], in_degree, queue)

    remaining = [plugin_dir for plugin_dir in plugin_dirs if plugin_dir not in ordered]
    return ordered + remaining


def _restore_one_symlink(link: dict, plugin_dir: Path, vars: dict[str, str]) -> None:
    destination = Path(_expand(link["to"], vars))
    backup = _symlink_backup_path(plugin_dir, destination)
    if destination.is_symlink():
        destination.unlink()
    if backup.exists() and not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(backup), str(destination))


def _remove_plugin_symlinks(symlinks: list[dict], plugin_dir: Path, vars: dict[str, str]) -> None:
    for link in symlinks:
        _restore_one_symlink(link, plugin_dir, vars)


def _restore_original_files(patches: list[dict], orig_dir: Path, vars: dict[str, str]) -> None:
    for patch_def in patches:
        target = Path(_expand(patch_def["file"], vars))
        orig_path = orig_dir / target.name
        if orig_path.exists():
            shutil.copy2(orig_path, target)


def _neutralize_plugin(plugin_dir: Path, vars: dict[str, str]) -> None:
    """Stop a plugin affecting the system: drop its symlinks, restore patched files, remove its
    linked libs and venv. Files in the plugin dir stay, so recover/reactivate can rebuild it."""
    manifest = json.loads((plugin_dir / "manifest.json").read_text())
    full_vars = {**vars, **_load_user_vars(plugin_dir)}
    ops = normalize_install(manifest.get("install", {}))
    _run_stop_commands(ops["stops"] + manifest.get("stop", []), full_vars)
    _remove_plugin_symlinks(ops["symlinks"], plugin_dir, full_vars)
    _restore_original_files(ops["patches"], plugin_dir / "patches_orig", full_vars)
    _remove_plugin_site_links(plugin_dir, full_vars)
    _remove_plugin_venv(plugin_dir.name, full_vars)


def _deactivate_plugin(plugin_dir: Path, vars: dict[str, str], reason: str) -> None:
    if (plugin_dir / "manifest.json").exists():
        _neutralize_plugin(plugin_dir, vars)
    (plugin_dir / _DEACTIVATED_MARKER).write_text(json.dumps({"reason": reason}))


def _missing_required_vars(manifest: dict, available: dict[str, str]) -> list[str]:
    specs = manifest.get("requires", {}).get("variables", [])
    return [spec["name"] for spec in specs if spec.get("required") and not available.get(spec["name"])]  # noqa: E501


def _apply_plugin(plugin_dir: Path, raw_inst: dict, inst: dict, full_vars: dict[str, str]) -> tuple[list[dict], list[str]]:  # noqa: E501
    patches_orig = plugin_dir / "patches_orig"
    if patches_orig.exists():
        shutil.rmtree(patches_orig)
    phase_log: list[dict] = [
        _render_templates(inst["templates"], plugin_dir, full_vars),
        _generate_service_scripts(raw_inst.get("service", []), plugin_dir, full_vars),
        _create_symlinks(inst["symlinks"], plugin_dir, full_vars),
        _apply_patches(inst["patches"], plugin_dir, full_vars),
    ]
    phase_log.extend(_provision_deps_phases(plugin_dir, full_vars))
    start_phase, deferred = _run_plugin_start_commands(inst["start"], full_vars)
    phase_log.append(start_phase)
    return phase_log, deferred


def _recover_one(
    plugin_dir: Path,
    manifest: dict,
    satisfied: set[str],
    all_provided: set[str],
    vars: dict[str, str],
) -> tuple[dict, list[str]]:
    plugin_id = plugin_dir.name
    missing_deps = [
        service for service in _required_services(manifest)
        if service in all_provided and service not in satisfied
    ]
    if missing_deps:
        reason = f"dependency not satisfied: {', '.join(missing_deps)}"
        return {"plugin_id": plugin_id, "ok": False, "skipped": True, "reason": reason, "log": []}, []  # noqa: E501

    full_vars = _with_plugin_venv({**vars, **_load_user_vars(plugin_dir)}, plugin_id)
    missing_vars = _missing_required_vars(manifest, full_vars)
    if missing_vars:
        reason = f"missing required variable(s): {', '.join(missing_vars)}; reinstall the plugin"
        return {"plugin_id": plugin_id, "ok": False, "skipped": False, "reason": reason, "log": []}, []  # noqa: E501

    raw_inst = manifest.get("install", {})
    inst = normalize_install(raw_inst)
    phase_log, deferred = _apply_plugin(plugin_dir, raw_inst, inst, full_vars)
    if all(phase["ok"] for phase in phase_log):
        satisfied.update(_provided_services(manifest))
        _clear_failure_markers(plugin_dir)
        ok_result = {"plugin_id": plugin_id, "ok": True, "skipped": False, "reason": "", "log": phase_log}  # noqa: E501
        return ok_result, deferred

    reason = "install phase failed"
    (plugin_dir / _RECOVERY_FAILURE_MARKER).write_text(json.dumps({"phases": phase_log}))
    _deactivate_plugin(plugin_dir, vars, reason)
    failed = {"plugin_id": plugin_id, "ok": False, "skipped": False, "reason": reason, "log": phase_log}  # noqa: E501
    return failed, []


# Auto-deactivate safety net (ADR-0036): when a deferred restart fails, read the service logs,
# attribute the failure to the plugin that placed the offending file/section/lib, deactivate it, and
# restart again. This is what keeps a printer usable after an OTA firmware update: a plugin that
# breaks against the new firmware peels itself off until a fixed version is published.


def _plugin_placement(plugin_dir: Path, vars: dict[str, str]) -> Placement:
    """What one installed plugin put on the system, as data for the attribution brain."""
    full_vars = {**vars, **_load_user_vars(plugin_dir)}
    ops = normalize_install(_manifest_at(plugin_dir).get("install", {}))
    destinations = [_expand(link["to"], full_vars) for link in ops["symlinks"]]
    modules = [_import_name(name) for name in _baked_top_level_names(plugin_dir)]
    return Placement(plugin_dir.name, destinations, modules)


def _build_attribution_index(vars: dict[str, str]) -> AttributionIndex:
    return build_attribution_index(
        [_plugin_placement(plugin_dir, vars) for plugin_dir in _installed_manifest_dirs()]
    )


def _op_context(kind: OperationKind, manifest: dict, plugin_id: str | None = None) -> OperationContext:  # noqa: E501
    """The operation the daemon is performing, for the safety net's report + last-resort blame."""
    return OperationContext(
        kind=kind,
        plugin_id=plugin_id if plugin_id is not None else manifest.get("name"),
        plugin_version=manifest.get("version"),
        publisher=manifest.get("publisher"),
    )


def _log_tail(vars: dict[str, str], key: str) -> str:
    path = vars.get(key)
    return _read_log_tail(Path(path)) if path else ""


def _gather_evidence(vars: dict[str, str]) -> FailureEvidence:
    """Probe the printer after a restart and build the attribution index: the data the brain judges.
    The Moonraker probe reads failed_components, so a reachable-but-broken component is caught."""
    klipper_reachable, _raw = _klipper_healthy()
    return FailureEvidence(
        klipper_reachable=klipper_reachable,
        klipper_log=_log_tail(vars, "KLIPPER_LOG"),
        moonraker=_probe_moonraker(),
        moonraker_log=_log_tail(vars, "MOONRAKER_LOG"),
        mqtt_up=_port_listening(_MQTT_PORT),
        index=_build_attribution_index(vars),
    )


def _recovery_result(deactivated: list[str], decision: Decision,
                     evidence: FailureEvidence, failure: FailureEvidence) -> dict:
    """Build the outcome. Health is judged on the FINAL evidence (did recovery work), but the
    reported log comes from the FIRST-failure evidence so the real traceback survives the recovery
    restarts that overwrite the live log."""
    ok = is_healthy(evidence)
    if deactivated:
        joined = ", ".join(deactivated)
        reason = (f"Auto-recovered: deactivated {joined} to keep the printer working" if ok
                  else f"Deactivated {joined} but the printer still did not recover")
    else:
        reason = decision.signal
    failure_log = _format_tails(failure.klipper_log, failure.moonraker_log)
    log_item = _item("captured service log for diagnosis", ok=ok, output=failure_log)
    result = {"plugin_id": "(services)", "ok": ok, "skipped": False, "reason": reason,
              "failure_log": failure_log,
              "log": [_phase("restart", "Restart services", [log_item])]}
    if deactivated:
        result["auto_deactivated"] = ", ".join(deactivated)
        result["fix_detail"] = decision.signal
    return result


def _auto_recover(deferred_cmds: list[str], vars: dict[str, str],
                  ctx: OperationContext, evidence: FailureEvidence) -> dict:
    """Walk the fixer chain: deactivate the named culprit, restart, re-probe, repeat until the
    printer is healthy or no plugin is left to blame."""
    failure = evidence
    deactivated: list[str] = []
    decision = decide(evidence, ctx, deactivated)
    for _attempt in range(len(_installed_manifest_dirs()) + 1):
        decision = decide(evidence, ctx, deactivated)
        if decision.culprit is None:
            break
        _deactivate_plugin(PLUGIN_ROOT / decision.culprit, vars,
                           f"auto-deactivated: {decision.signal}")
        deactivated.append(decision.culprit)
        _run_restart_batch(deferred_cmds, vars)
        evidence = _gather_evidence(vars)
        if is_healthy(evidence):
            break
    return _recovery_result(deactivated, decision, evidence, failure)


def _touches_core_service(deferred_cmds: list[str]) -> bool:
    """Only a Klipper/Moonraker restart needs the safety net; a plugin-service or nginx bounce does
    not put the printer's base functions at risk, so we skip the probe + recovery for those."""
    return any(_restarts_klipper(cmd) or _restarts_moonraker(cmd) for cmd in deferred_cmds)


def _restart_services(deferred_cmds: list[str], vars: dict[str, str], ctx: OperationContext) -> dict:  # noqa: E501
    """Do the restart, then ask the safety net to verify and recover. The daemon does the thing; the
    net watches (incl. failed components), acts (deactivate), and reports."""
    result = _run_restart_batch(deferred_cmds, vars)
    if not _touches_core_service(deferred_cmds):
        return result
    evidence = _gather_evidence(vars)
    if is_healthy(evidence):
        return result
    return _auto_recover(deferred_cmds, vars, ctx, evidence)


def _restart_phases(deferred_cmds: list[str], vars: dict[str, str], ctx: OperationContext) -> list[dict]:  # noqa: E501
    """Restart the deferred core services THROUGH the safety net and return the outcome as
    install/reconfigure phases. A plugin that breaks Klipper/Moonraker is deactivated so the printer
    keeps working; the captured service log and what was disabled are surfaced as phases."""
    if not deferred_cmds:
        return []
    result = _restart_services(deferred_cmds, vars, ctx)
    phases = list(result.get("log", []))
    deactivated = result.get("auto_deactivated")
    if not deactivated:
        return phases
    target_disabled = ctx.plugin_id in [name.strip() for name in deactivated.split(",")]
    detail = result.get("fix_detail", "")
    # State the FACT only; the app phrases user-facing advice per user tier and offers the report.
    if target_disabled:
        label = f"{ctx.plugin_id} was disabled to keep the printer working ({detail})."
    else:
        label = f"Disabled {deactivated} to keep the printer working ({detail})."
    phases.append(_phase(
        "auto-recovery", "Safety auto-recovery",
        [_item(label, ok=not target_disabled, output=result.get("failure_log", ""))],
    ))
    return phases


def recover(vars: dict[str, str]) -> list[dict]:
    """Re-apply all installed, non-deactivated plugins after OTA. Returns per-plugin results."""
    _guard_no_print("recover plugins")
    if not PLUGIN_ROOT.exists():
        return []
    plugin_dirs = [
        plugin_dir for plugin_dir in PLUGIN_ROOT.iterdir()
        if plugin_dir.is_dir()
        and (plugin_dir / "manifest.json").exists()
        and not (plugin_dir / _DEACTIVATED_MARKER).exists()
    ]
    if not plugin_dirs:
        return []
    ordered = _topo_sort(plugin_dirs)
    manifests = {
        plugin_dir: json.loads((plugin_dir / "manifest.json").read_text())
        for plugin_dir in ordered
    }
    all_provided: set[str] = set()
    for manifest in manifests.values():
        all_provided.update(_provided_services(manifest))
    satisfied: set[str] = set()
    results: list[dict] = []
    deferred_restarts: list[str] = []
    for plugin_dir in ordered:
        result, deferred = _recover_one(plugin_dir, manifests[plugin_dir], satisfied, all_provided, vars)  # noqa: E501
        results.append(result)
        if result["ok"]:
            deferred_restarts.extend(deferred)
    unique_restarts = list(dict.fromkeys(deferred_restarts))
    if unique_restarts:
        results.append(_restart_services(unique_restarts, vars, OperationContext(OperationKind.RECOVER)))  # noqa: E501
    return results


def _read_manifest(package_path: Path) -> dict:
    with zipfile.ZipFile(package_path) as archive:
        return json.loads(archive.read("manifest.json"))


def _guard_batch_no_print(manifests: list[dict]) -> None:
    """Refuse the whole batch up front if any update restarts Klipper/Moonraker mid-print."""
    if not any(_manifest_restarts_services(manifest) for manifest in manifests):
        return
    active, state = _print_active()
    if not active:
        return
    raise ValueError(
        f"Cannot update plugins while a print is {state}: some updates restart Klipper or "
        "Moonraker, which would interrupt the print. Try again when the printer is idle."
    )


def _apply_install_deferred(plugin_dir: Path, manifest: dict, vars: dict[str, str]) -> tuple[list[dict], list[str]]:  # noqa: E501
    """Run a fresh install's file phases, deferring service restarts to the batch end."""
    raw_inst = manifest.get("install", {})
    inst = normalize_install(raw_inst)
    log = [
        _apply_modes(plugin_dir, manifest.get("files", [])),
        _create_dirs(inst["dirs"], vars),
        _render_templates(inst["templates"], plugin_dir, vars),
        _generate_service_scripts(raw_inst.get("service", []), plugin_dir, vars),
        _create_symlinks(inst["symlinks"], plugin_dir, vars),
        _apply_patches(inst["patches"], plugin_dir, vars),
        _fix_ownership(plugin_dir, vars.get("RUNTIME_USER", "")),
    ]
    log.extend(_provision_deps_phases(plugin_dir, vars))
    start_phase, deferred = _run_plugin_start_commands(inst["start"], vars)
    log.append(start_phase)
    return log, deferred


def _update_one(base_vars: dict[str, str], package_path: Path, user_vars: dict[str, str]) -> tuple[dict, list[str]]:  # noqa: E501
    manifest, plugin_dir, file_count = _unpack_package(package_path)
    plugin_id = manifest["name"]
    full_vars = _with_plugin_venv({**base_vars, **user_vars}, plugin_id)
    _persist_user_vars(plugin_dir, user_vars)
    extract = _phase("extract", "Unpack", [_item(f"Extracted {file_count} files", ok=True)])
    phases, deferred = _apply_install_deferred(plugin_dir, manifest, full_vars)
    log = [extract, *phases]
    ok = all(phase["ok"] for phase in log)
    if ok:
        _clear_failure_markers(plugin_dir)
    reason = "" if ok else "update phase failed"
    result = {"plugin_id": plugin_id, "ok": ok, "skipped": False, "reason": reason, "log": log}
    return result, (deferred if ok else [])


def update_batch(
    base_vars: dict[str, str],
    package_paths: list[Path],
    vars_by_id: dict[str, dict[str, str]],
) -> list[dict]:
    """Update several plugins, restarting affected services only once at the end.

    Each package is unpacked and re-applied (templates, symlinks, patches, inline start commands);
    init-script and nginx restarts are deferred, deduped, and run once, then Klipper and Moonraker
    are awaited healthy. Mirrors recover's deferred-restart batching for the update path. Packages
    are applied in the order given, so callers pass dependencies before their dependents.
    """
    if not package_paths:
        return []
    specs = [(package_path, _read_manifest(package_path)) for package_path in package_paths]
    _guard_batch_no_print([manifest for _, manifest in specs])
    results: list[dict] = []
    deferred_restarts: list[str] = []
    for package_path, manifest in specs:
        user_vars = vars_by_id.get(manifest["name"], {})
        result, deferred = _update_one(base_vars, package_path, user_vars)
        results.append(result)
        deferred_restarts.extend(deferred)
    unique_restarts = list(dict.fromkeys(deferred_restarts))
    if unique_restarts:
        only = specs[0][1]["name"] if len(specs) == 1 else None
        ctx = OperationContext(OperationKind.UPDATE, plugin_id=only)
        results.append(_restart_services(unique_restarts, base_vars, ctx))
    return results


def _uninstall_from_manifest(manifest_path: Path, plugin_dir: Path, vars: dict[str, str]) -> None:
    manifest = json.loads(manifest_path.read_text())
    install_spec = normalize_install(manifest.get("install", {}))
    full_vars = {**vars, **_load_user_vars(plugin_dir)}
    _run_stop_commands(install_spec["stops"] + manifest.get("stop", []), full_vars)
    _remove_plugin_symlinks(install_spec["symlinks"], plugin_dir, full_vars)
    _restore_original_files(install_spec["patches"], plugin_dir / "patches_orig", full_vars)


def _remove_plugin_venv(plugin_id: str, vars: dict[str, str]) -> None:
    bespok3d_root = vars.get("BESPOK3D", "")
    if bespok3d_root:
        shutil.rmtree(python_env.plugin_venv_path(bespok3d_root, plugin_id), ignore_errors=True)


def _remove_one(plugin_dir: Path, vars: dict[str, str]) -> None:
    manifest_path = plugin_dir / "manifest.json"
    if manifest_path.exists():
        _uninstall_from_manifest(manifest_path, plugin_dir, vars)
    _remove_plugin_site_links(plugin_dir, vars)
    _remove_plugin_venv(plugin_dir.name, vars)
    shutil.rmtree(plugin_dir)


def _remove_with_dependents(plugin_id: str, vars: dict[str, str], removed: list[str]) -> None:
    for dependent in installed_dependents(plugin_id):
        if dependent not in removed:
            _remove_with_dependents(dependent, vars, removed)
    plugin_dir = PLUGIN_ROOT / plugin_id
    if plugin_dir.exists() and plugin_id not in removed:
        _remove_one(plugin_dir, vars)
        removed.append(plugin_id)


def _removal_restart_commands(plugin_ids: list[str], vars: dict[str, str]) -> list[str]:
    """Core-service restart hooks declared by the plugins being removed, expanded and deduped.

    Install runs a plugin's `restart` hooks so its config/extra takes effect; uninstall must run the
    same hooks so the REMOVAL takes effect (Klipper keeps a now-deleted [section] loaded, and nginx
    keeps a removed web location, until the service restarts).
    """
    commands: list[str] = []
    for plugin_id in plugin_ids:
        manifest_path = PLUGIN_ROOT / plugin_id / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text())
        for hook in manifest.get("install", {}).get("restart", []):
            command = RESTART_HOOKS.get(hook)
            if command:
                commands.append(_expand(command, vars))
    return list(dict.fromkeys(commands))


def uninstall(plugin_id: str, vars: dict[str, str], cascade: bool = False) -> list[str]:
    """Remove a plugin. Refuses if installed dependents need it, unless cascade removes them too.

    Returns the ids removed, dependents first, target last.
    """
    plugin_dir = PLUGIN_ROOT / plugin_id
    if not plugin_dir.exists():
        raise FileNotFoundError(plugin_id)
    dependents = installed_dependents(plugin_id)
    if dependents and not cascade:
        raise DependentsError(plugin_id, dependents)
    _guard_no_print_for_removal([plugin_id, *dependents])
    restart_commands = _removal_restart_commands([*dependents, plugin_id], vars)
    removed: list[str] = []
    _remove_with_dependents(plugin_id, vars, removed)
    if restart_commands:
        _restart_services(restart_commands, vars, OperationContext(OperationKind.UNINSTALL, plugin_id))  # noqa: E501
    return removed


def _guard_no_print_for_removal(plugin_ids: list[str]) -> None:
    """Refuse removing any plugin that would bounce a core/display service while printing/paused."""
    for plugin_id in plugin_ids:
        manifest_path = PLUGIN_ROOT / plugin_id / "manifest.json"
        if manifest_path.exists():
            _guard_no_print_during_restart(json.loads(manifest_path.read_text()), action="remove")


_GLOBAL_DEACTIVATED_MARKER = "etc/deactivated"


def _remove_include_line(cfg_path: Path, pattern: str) -> None:
    if not cfg_path.exists():
        return
    text = cfg_path.read_text()
    cfg_path.write_text(
        "".join(line for line in text.splitlines(keepends=True) if pattern not in line)
    )


def _deactivate_plugin_dir(plugin_dir: Path, vars: dict[str, str]) -> None:
    if not plugin_dir.is_dir() or not (plugin_dir / "manifest.json").exists():
        return
    _neutralize_plugin(plugin_dir, vars)


def _deactivate_plugins_in(plugin_root: Path, vars: dict[str, str]) -> None:
    if not plugin_root.exists():
        return
    for plugin_dir in plugin_root.iterdir():
        _deactivate_plugin_dir(plugin_dir, vars)


def _write_deactivated_marker(data_root: Path) -> None:
    marker = data_root / _GLOBAL_DEACTIVATED_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()


def deactivate_all(vars: dict[str, str]) -> None:
    """Stop all plugins and remove config hooks; leave plugin files intact."""
    _guard_no_print("deactivate plugins")
    data_root = Path(vars["BESPOK3D"])
    _deactivate_plugins_in(data_root / "usr/local/plugins", vars)
    _remove_include_line(Path(vars["PRINTER_CFG"]), "[include bespok3d/klipper")
    _remove_include_line(Path(vars["MOONRAKER_CFG"]), "[include bespok3d/moonraker")
    _write_deactivated_marker(data_root)


def _uninstall_plugins_in(plugin_root: Path, vars: dict[str, str]) -> None:
    if not plugin_root.exists():
        return
    plugin_ids = [plugin_dir.name for plugin_dir in plugin_root.iterdir() if plugin_dir.is_dir()]
    for plugin_id in plugin_ids:
        try:
            uninstall(plugin_id, vars)
        except Exception:  # noqa: BLE001
            pass


def _prune_links_and_empty_dirs(root: Path) -> None:
    """Remove our symlinks and any directories left empty, but keep real files.

    The `config/bespok3d` directory is intentionally preserved: a user may have dropped
    their own .cfg files in it. We only take back what Bespok3d put there (symlinks).
    """
    if not root.is_dir():
        return
    for child in sorted(root.iterdir()):
        if child.is_symlink():
            child.unlink()
        elif child.is_dir():
            _prune_links_and_empty_dirs(child)
    if not any(root.iterdir()):
        root.rmdir()


def _remove_bespok3d_config_dir(vars: dict[str, str]) -> None:
    config_dir = Path(vars.get("BESPOK3D_KLIPPER", "")).parent
    if config_dir.name == "bespok3d":
        _prune_links_and_empty_dirs(config_dir)


def teardown(vars: dict[str, str]) -> None:
    """Uninstall all plugins and remove config hooks; SSH caller removes the workspace."""
    # Guard at the top: the per-plugin uninstall guard is swallowed by _uninstall_plugins_in.
    _guard_no_print("remove all plugins")
    data_root = Path(vars["BESPOK3D"])
    _uninstall_plugins_in(data_root / "usr/local/plugins", vars)
    _remove_include_line(Path(vars["PRINTER_CFG"]), "[include bespok3d/klipper")
    _remove_include_line(Path(vars["MOONRAKER_CFG"]), "[include bespok3d/moonraker")
    _remove_bespok3d_config_dir(vars)
