"""
Package operations: install, uninstall.

A .b3 package is a zip containing manifest.json plus the plugin file tree.
Install is manifest-driven: dirs, symlinks, and unified-diff patches.
Signature verification is deferred until packages are signed.
"""

import json
import os
import shutil
import subprocess
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from ..intent import (
    RESTART_HOOKS,
    is_service_action,
    normalize_install,
    restarts_klipper,
    restarts_moonraker,
)
from ..python_env import import_name
from ..results import item as _item
from ..results import phase as _phase
from ..safety import (
    Decision,
    FailureEvidence,
    OperationContext,
    OperationKind,
    decide,
    is_healthy,
)
from ..safety.attribution import AttributionIndex, Placement
from ..safety.attribution import build_index as build_attribution_index
from ..safety.health import MQTT_PORT as _MQTT_PORT
from ..safety.health import klipper_healthy as _klipper_healthy
from ..safety.health import port_listening as _port_listening
from ..safety.health import probe_moonraker as _probe_moonraker
from ..safety.health import run_restart_batch as _run_restart_batch
from ..safety.logs import format_tails as _format_tails
from ..safety.logs import read_log_tail as _read_log_tail
from ..shell import run_one_command as _run_one_start_command
from ..shell import start_env as _start_env
from .errors import ConflictError, DependentsError
from .patches import apply_patches, restore_original_files
from .placement import (
    apply_modes,
    create_dirs,
    create_symlinks,
    remove_plugin_symlinks,
)
from .print_guard import (
    guard_batch_no_print,
    guard_no_print,
    guard_no_print_during_restart,
    guard_no_print_for_removal,
)
from .python_deps import (
    baked_top_level_names,
    provision_deps_phases,
    reject_conflicting_dep_files,
    reject_unbaked_deps,
    remove_plugin_site_links,
    remove_plugin_venv,
)
from .services import generate_service_scripts
from .templates import render_templates
from .user_vars import (
    USER_VARS_FILE,  # noqa: F401  re-export for tests
    expand,
    load_user_vars,
    missing_required_vars,
    persist_user_vars,
    validate_user_vars,  # noqa: F401  re-export for api.routes
    with_plugin_venv,
)

_DATA_ROOT = Path(os.environ.get("BESPOK3D_DATA_ROOT", "/userdata/bespok3d"))
PLUGIN_ROOT = _DATA_ROOT / "usr/local/plugins"

def _run_plugin_start_commands(cmds: list[str], vars: dict[str, str]) -> tuple[dict, list[str]]:
    """Run a plugin's plugin-specific start commands; defer Klipper/Moonraker restarts.

    Returns the start phase plus the deferred service-restart commands so the caller can
    run them once at the end of a batch instead of bouncing Klipper/Moonraker per plugin.
    """
    env = _start_env()
    expanded_cmds = [expand(cmd, vars) for cmd in cmds]
    immediate = [cmd for cmd in expanded_cmds if not is_service_action(cmd)]
    deferred = [cmd for cmd in expanded_cmds if is_service_action(cmd)]
    items = [_run_one_start_command(cmd, env) for cmd in immediate]
    return _phase("start", "Start commands", items), deferred


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
        guard_no_print_during_restart(manifest)
        plugin_dir = PLUGIN_ROOT / manifest["name"]
        plugin_dir.mkdir(parents=True, exist_ok=True)
        # doc/ is catalog documentation, never deployed: printer space is at a premium.
        members = [name for name in zf.namelist() if not _is_doc_member(name)]
        _extract_members(zf, plugin_dir, members)
        file_count = len(members)
    shutil.rmtree(plugin_dir / "doc", ignore_errors=True)
    reject_conflicting_dep_files(plugin_dir)
    reject_unbaked_deps(plugin_dir)
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
        _emit(apply_modes(plugin_dir, manifest.get("files", [])), notify),
        _emit(create_dirs(inst["dirs"], full_vars), notify),
        _emit(render_templates(inst["templates"], plugin_dir, full_vars), notify),
        _emit(generate_service_scripts(raw_inst.get("service", []), plugin_dir, full_vars), notify),  # noqa: E501
        _emit(create_symlinks(inst["symlinks"], plugin_dir, full_vars), notify),
        _emit(apply_patches(inst["patches"], plugin_dir, full_vars), notify),
        _emit(_fix_ownership(plugin_dir, full_vars.get("RUNTIME_USER", "")), notify),
    ]
    phases.extend(_emit(phase, notify) for phase in provision_deps_phases(PLUGIN_ROOT, plugin_dir, full_vars))  # noqa: E501
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

    persist_user_vars(plugin_dir, user_vars or {})
    full_vars = with_plugin_venv(vars, plugin_id)
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
    guard_no_print_during_restart(manifest)

    full_vars = with_plugin_venv(vars, plugin_id)
    inst = normalize_install(manifest.get("install", {}))
    persist_user_vars(plugin_dir, user_vars)
    start_phase, deferred = _run_plugin_start_commands(inst.get("start", []), full_vars)
    phases = [
        render_templates(inst.get("templates", []), plugin_dir, full_vars),
        _fix_ownership(plugin_dir, full_vars.get("RUNTIME_USER", "")),
        start_phase,
    ]
    phases.extend(_restart_phases(deferred, full_vars, _op_context(OperationKind.RECONFIGURE, manifest)))  # noqa: E501
    return plugin_id, phases


def _run_stop_commands(cmds: list[str], vars: dict[str, str]) -> None:
    env = {**os.environ, "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}
    for cmd in cmds:
        subprocess.run(expand(cmd, vars), shell=True, capture_output=True, check=False, env=env)


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
    return cast(dict, json.loads((plugin_dir / "manifest.json").read_text()))


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


def _neutralize_plugin(plugin_dir: Path, vars: dict[str, str]) -> None:
    """Stop a plugin affecting the system: drop its symlinks, restore patched files, remove its
    linked libs and venv. Files in the plugin dir stay, so recover/reactivate can rebuild it."""
    manifest = json.loads((plugin_dir / "manifest.json").read_text())
    full_vars = {**vars, **load_user_vars(plugin_dir)}
    ops = normalize_install(manifest.get("install", {}))
    _run_stop_commands(ops["stops"] + manifest.get("stop", []), full_vars)
    remove_plugin_symlinks(ops["symlinks"], plugin_dir, full_vars)
    restore_original_files(ops["patches"], plugin_dir / "patches_orig", full_vars)
    remove_plugin_site_links(plugin_dir, full_vars)
    remove_plugin_venv(plugin_dir.name, full_vars)


def _deactivate_plugin(plugin_dir: Path, vars: dict[str, str], reason: str) -> None:
    if (plugin_dir / "manifest.json").exists():
        _neutralize_plugin(plugin_dir, vars)
    (plugin_dir / _DEACTIVATED_MARKER).write_text(json.dumps({"reason": reason}))


def _apply_plugin(plugin_dir: Path, raw_inst: dict, inst: dict, full_vars: dict[str, str]) -> tuple[list[dict], list[str]]:  # noqa: E501
    patches_orig = plugin_dir / "patches_orig"
    if patches_orig.exists():
        shutil.rmtree(patches_orig)
    phase_log: list[dict] = [
        render_templates(inst["templates"], plugin_dir, full_vars),
        generate_service_scripts(raw_inst.get("service", []), plugin_dir, full_vars),
        create_symlinks(inst["symlinks"], plugin_dir, full_vars),
        apply_patches(inst["patches"], plugin_dir, full_vars),
    ]
    phase_log.extend(provision_deps_phases(PLUGIN_ROOT, plugin_dir, full_vars))
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

    full_vars = with_plugin_venv({**vars, **load_user_vars(plugin_dir)}, plugin_id)
    missing_vars = missing_required_vars(manifest, full_vars)
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
    full_vars = {**vars, **load_user_vars(plugin_dir)}
    ops = normalize_install(_manifest_at(plugin_dir).get("install", {}))
    destinations = [expand(link["to"], full_vars) for link in ops["symlinks"]]
    modules = [import_name(name) for name in baked_top_level_names(plugin_dir)]
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
    return any(restarts_klipper(cmd) or restarts_moonraker(cmd) for cmd in deferred_cmds)


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
    guard_no_print("recover plugins")
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
        return cast(dict, json.loads(archive.read("manifest.json")))


def _apply_install_deferred(plugin_dir: Path, manifest: dict, vars: dict[str, str]) -> tuple[list[dict], list[str]]:  # noqa: E501
    """Run a fresh install's file phases, deferring service restarts to the batch end."""
    raw_inst = manifest.get("install", {})
    inst = normalize_install(raw_inst)
    log = [
        apply_modes(plugin_dir, manifest.get("files", [])),
        create_dirs(inst["dirs"], vars),
        render_templates(inst["templates"], plugin_dir, vars),
        generate_service_scripts(raw_inst.get("service", []), plugin_dir, vars),
        create_symlinks(inst["symlinks"], plugin_dir, vars),
        apply_patches(inst["patches"], plugin_dir, vars),
        _fix_ownership(plugin_dir, vars.get("RUNTIME_USER", "")),
    ]
    log.extend(provision_deps_phases(PLUGIN_ROOT, plugin_dir, vars))
    start_phase, deferred = _run_plugin_start_commands(inst["start"], vars)
    log.append(start_phase)
    return log, deferred


def _update_one(base_vars: dict[str, str], package_path: Path, user_vars: dict[str, str]) -> tuple[dict, list[str]]:  # noqa: E501
    manifest, plugin_dir, file_count = _unpack_package(package_path)
    plugin_id = manifest["name"]
    full_vars = with_plugin_venv({**base_vars, **user_vars}, plugin_id)
    persist_user_vars(plugin_dir, user_vars)
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
    guard_batch_no_print([manifest for _, manifest in specs])
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
    full_vars = {**vars, **load_user_vars(plugin_dir)}
    _run_stop_commands(install_spec["stops"] + manifest.get("stop", []), full_vars)
    remove_plugin_symlinks(install_spec["symlinks"], plugin_dir, full_vars)
    restore_original_files(install_spec["patches"], plugin_dir / "patches_orig", full_vars)


def _remove_one(plugin_dir: Path, vars: dict[str, str]) -> None:
    manifest_path = plugin_dir / "manifest.json"
    if manifest_path.exists():
        _uninstall_from_manifest(manifest_path, plugin_dir, vars)
    remove_plugin_site_links(plugin_dir, vars)
    remove_plugin_venv(plugin_dir.name, vars)
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
                commands.append(expand(command, vars))
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
    guard_no_print_for_removal(PLUGIN_ROOT, [plugin_id, *dependents])
    restart_commands = _removal_restart_commands([*dependents, plugin_id], vars)
    removed: list[str] = []
    _remove_with_dependents(plugin_id, vars, removed)
    if restart_commands:
        _restart_services(restart_commands, vars, OperationContext(OperationKind.UNINSTALL, plugin_id))  # noqa: E501
    return removed


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
    guard_no_print("deactivate plugins")
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
    guard_no_print("remove all plugins")
    data_root = Path(vars["BESPOK3D"])
    _uninstall_plugins_in(data_root / "usr/local/plugins", vars)
    _remove_include_line(Path(vars["PRINTER_CFG"]), "[include bespok3d/klipper")
    _remove_include_line(Path(vars["MOONRAKER_CFG"]), "[include bespok3d/moonraker")
    _remove_bespok3d_config_dir(vars)
