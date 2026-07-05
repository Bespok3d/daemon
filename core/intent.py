"""Translate the intent-based install block into the mechanism operations the executor runs.

ADR-0026 frames the manifest as four named sections that declare WHAT lands where, never a
path or a mechanism: `place` (a payload file of a destination class), `instrument` (a carried
diff against a pre-existing file), `service` (a managed long-running process), and `restart`
(core-service hooks). The adapter owns the class-to-(path, mechanism) mapping.

The daemon owns no device path or restart command: a placement or instrument names a CLASS and a
restart names a HOOK, and the jinni resolves each (`jinni/base.py` for the bespok3d layout,
`jinni/klipper.py` for klipper conventions, the adapter for genuine device restart commands). This
module maps the new sections to the legacy `{symlinks, templates, patches, start, dirs}` operations
the current executor runs, merging in any legacy keys a not-yet-migrated manifest still carries.
"""
from pathlib import PurePosixPath

from core import conditions, jinni_client
from core.autostart import autostart_additions, kmodule_ops, service_ops

DATA_DIR_TEMPLATE = "$BESPOK3D/var/lib/{name}"


def _placement_target(placement: dict) -> tuple[str, str]:
    target_name = placement.get("name") or PurePosixPath(placement["src"]).name
    destination = jinni_client.placement_destination(placement["class"], target_name)
    return destination, target_name


def _placement_ops(placement: dict) -> tuple[dict | None, dict]:
    """Return (template_op_or_None, symlink_op) realizing one placement.

    A `render` placement first writes the variable-substituted file beside the template inside
    the plugin dir, then symlinks that rendered file into the destination.
    """
    source = placement["src"]
    destination, target_name = _placement_target(placement)
    if not placement.get("render"):
        return None, {"from": source, "to": destination}
    rendered = str(PurePosixPath(source).parent / target_name)
    return {"from": source, "to": rendered}, {"from": rendered, "to": destination}


def _instrument_op(entry: dict) -> dict:
    destination = jinni_client.instrument_destination(entry["class"], entry["name"])
    return {"file": destination, "patch": entry["diff"]}


def _placement_additions(placements: list[dict]) -> tuple[list[dict], list[dict]]:
    templates: list[dict] = []
    symlinks: list[dict] = []
    for placement in placements:
        template_op, symlink_op = _placement_ops(placement)
        if template_op is not None:
            templates.append(template_op)
        symlinks.append(symlink_op)
    return templates, symlinks


def _restart_commands(hooks: list[str]) -> list[str]:
    commands = []
    for hook in hooks:
        command = jinni_client.restart_command(hook)
        if command is None:
            raise ValueError(f"unsupported restart hook: {hook}")
        commands.append(command)
    return commands


def _require_stable_variant_names(place_entries: list[dict]) -> None:
    """A variant-carrying place entry must name its target. Without a truthy `name` the destination
    is basename(src), which differs per variant; teardown re-resolves against the CURRENT facts, so
    a symlink placed under one variant could leak under another once facts change. A falsy name
    (null / empty) is as unstable as a missing one, so reject it too (a variant entry has no
    top-level `src` to fall back on). Fail loud at install, never leak later."""
    unstable = [entry for entry in place_entries if "variants" in entry and not entry.get("name")]
    if unstable:
        raise ValueError("a place entry with variants must declare an explicit name")


def _kernel_module_names(place_entries: list[dict]) -> set[str]:
    return {
        entry.get("name") or PurePosixPath(entry["src"]).name
        for entry in place_entries
        if entry.get("class") == "kernel-module"
    }


def _require_kmodule_placed(place_entries: list[dict], kmodules: list[dict]) -> None:
    """Every `install.kmodule` must load a `.ko` the plugin DECLARES a place for. `module` names a
    `kernel-module` placement's target (`name`, or basename(src)); a kmodule naming a `.ko` no place
    entry declares is an authoring typo, so fail loud at install. This checks the manifest, not a
    per-box resolution: a printer matching no variant of that placement drops it (via
    `resolve_variants`) and the still-emitted load fails closed to a safe deactivate, which the
    packet-5 autofixer classifies. Precedent for the loud check: `_require_stable_variant_names`."""
    placed = _kernel_module_names(place_entries)
    missing = sorted(module["module"] for module in kmodules if module["module"] not in placed)
    if missing:
        raise ValueError(f"install.kmodule names modules no place entry ships: {missing}")


def normalize_install(install: dict, facts: dict[str, str] | None = None) -> dict:
    """Merge any legacy install keys with the translated intent sections into legacy ops. `facts`
    are the device facts the variant pre-pass selects on (`jinni_client.variant_facts()`); absent
    facts resolve as a generic box, so only catch-all variants survive.

    A kernel-module load lands in its own `module_loads` list, not `start`: the daemon owns the
    ordering (modules load BEFORE services, and before any deferred core-service restart), so a
    module load runs immediately in its install phase rather than being classified and batched."""
    _require_stable_variant_names(install.get("place", []))
    _require_kmodule_placed(install.get("place", []), install.get("kmodule", []))
    resolved = conditions.resolve_variants(install, facts or {})
    place_templates, place_symlinks = _placement_additions(resolved.get("place", []))
    service_symlinks, service_starts, service_stops = autostart_additions(
        resolved.get("service", []), service_ops
    )
    module_symlinks, module_loads, module_unloads = autostart_additions(
        resolved.get("kmodule", []), kmodule_ops
    )
    # Parallel to module_loads: autostart_additions emits one load per autoload kmodule, in order,
    # so filtering the same list the same way gives the in-kernel name for each load command, which
    # the load-failure classifier keys on.
    module_load_names = [entry["name"] for entry in resolved.get("kmodule", []) if entry.get("autoload")]  # noqa: E501
    data_dirs = [DATA_DIR_TEMPLATE.format(name=name) for name in resolved.get("data", [])]
    patches = [_instrument_op(entry) for entry in resolved.get("instrument", [])]
    restart_commands = _restart_commands(resolved.get("restart", []))
    return {
        "dirs": [*resolved.get("dirs", []), *data_dirs],
        "templates": [*resolved.get("templates", []), *place_templates],
        "symlinks": [
            *resolved.get("symlinks", []), *place_symlinks, *service_symlinks, *module_symlinks
        ],
        "patches": [*resolved.get("patches", []), *patches],
        "start": [*resolved.get("start", []), *service_starts, *restart_commands],
        "stops": [*service_stops, *module_unloads],
        "module_loads": module_loads,
        "module_load_names": module_load_names,
    }
