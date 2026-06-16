"""Gather the printer's post-restart state as data for the safety net to judge.

What one plugin placed (symlink destinations, baked modules) becomes the attribution index; the
Moonraker probe reads failed_components so a reachable-but-broken component is caught. No verdict
here: this module only builds the evidence; core.safety decides, restart acts.
"""

from pathlib import Path

from ... import jinni_client
from ...intent import normalize_install
from ...python_env import import_name
from ...safety import FailureEvidence
from ...safety.attribution import AttributionIndex, Placement
from ...safety.attribution import build_index as build_attribution_index
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


def gather_evidence(plugin_root: Path, vars: dict[str, str]) -> FailureEvidence:
    """Ask the jinni for the health verdict and build the attribution index: the data the brain
    judges. The jinni's report carries the failed components AND the failure signals it read from
    the device logs; the daemon opens no log, it only maps a signal to the plugin that placed it."""
    return FailureEvidence(
        health=jinni_client.health(),
        index=_build_attribution_index(plugin_root, vars),
    )
