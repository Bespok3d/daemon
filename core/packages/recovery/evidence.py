# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
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
from ..baked_deps import baked_top_level_names
from ..manifest import installed_manifest_dirs, readable_manifest
from ..user_vars import expand, load_user_vars


def _plugin_placement(plugin_dir: Path, manifest: dict, vars: dict[str, str],
                      facts: dict[str, str]) -> Placement:
    """What one installed plugin put on the system, as data for the attribution brain. Resolved with
    the live facts, so a variant-placed file is attributed to the variant that placed it."""
    full_vars = {**vars, **load_user_vars(plugin_dir)}
    ops = normalize_install(manifest.get("install", {}), facts)
    destinations = [expand(link["to"], full_vars) for link in ops["symlinks"]]
    modules = [import_name(name) for name in baked_top_level_names(plugin_dir)]
    return Placement(plugin_dir.name, destinations, modules)


def _build_attribution_index(
    plugin_root: Path, vars: dict[str, str], facts: dict[str, str]
) -> AttributionIndex:
    """A plugin whose manifest cannot be read placed nothing anyone can attribute, so it is left out
    and every other plugin's evidence is still built. Recovery names it in its own report."""
    read = {plugin_dir: readable_manifest(plugin_dir)
            for plugin_dir in installed_manifest_dirs(plugin_root)}
    return build_attribution_index(
        [_plugin_placement(plugin_dir, manifest, vars, facts)
         for plugin_dir, manifest in read.items() if manifest is not None]
    )


def gather_evidence(plugin_root: Path, vars: dict[str, str]) -> FailureEvidence:
    """Ask the jinni for the health verdict and build the attribution index: the data the brain
    judges. The jinni's report carries the failed components AND the failure signals it read from
    the device logs; the daemon opens no log, it only maps a signal to the plugin that placed it."""
    facts = jinni_client.variant_facts()
    return FailureEvidence(
        health=jinni_client.health(),
        index=_build_attribution_index(plugin_root, vars, facts),
    )
