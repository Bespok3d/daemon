"""Gather the printer's post-restart state as data for the safety net to judge.

What one plugin placed (symlink destinations, baked modules) becomes the attribution index; the
Moonraker probe reads failed_components so a reachable-but-broken component is caught. No verdict
here: this module only builds the evidence; core.safety decides, restart acts.
"""

from pathlib import Path

from ...intent import normalize_install
from ...python_env import import_name
from ...safety import FailureEvidence
from ...safety.attribution import AttributionIndex, Placement
from ...safety.attribution import build_index as build_attribution_index
from ...safety.logs import read_log_tail
from ...safety.probe.klipper import klipper_healthy
from ...safety.probe.moonraker import probe_moonraker
from ...safety.probe.reach import MQTT_PORT, port_listening
from ..manifest import installed_manifest_dirs, manifest_at
from ..python_deps import baked_top_level_names
from ..user_vars import expand, load_user_vars


def _plugin_placement(plugin_dir: Path, vars: dict[str, str]) -> Placement:
    """What one installed plugin put on the system, as data for the attribution brain."""
    full_vars = {**vars, **load_user_vars(plugin_dir)}
    ops = normalize_install(manifest_at(plugin_dir).get("install", {}))
    destinations = [expand(link["to"], full_vars) for link in ops["symlinks"]]
    modules = [import_name(name) for name in baked_top_level_names(plugin_dir)]
    return Placement(plugin_dir.name, destinations, modules)


def _build_attribution_index(plugin_root: Path, vars: dict[str, str]) -> AttributionIndex:
    return build_attribution_index(
        [_plugin_placement(plugin_dir, vars) for plugin_dir in installed_manifest_dirs(plugin_root)]
    )


def _log_tail(vars: dict[str, str], key: str) -> str:
    path = vars.get(key)
    return read_log_tail(Path(path)) if path else ""


def gather_evidence(plugin_root: Path, vars: dict[str, str]) -> FailureEvidence:
    """Probe the printer after a restart and build the attribution index: the data the brain judges.
    The Moonraker probe reads failed_components, so a reachable-but-broken component is caught."""
    klipper_reachable, _raw = klipper_healthy()
    return FailureEvidence(
        klipper_reachable=klipper_reachable,
        klipper_log=_log_tail(vars, "KLIPPER_LOG"),
        moonraker=probe_moonraker(),
        moonraker_log=_log_tail(vars, "MOONRAKER_LOG"),
        mqtt_up=port_listening(MQTT_PORT),
        index=_build_attribution_index(plugin_root, vars),
    )
