# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Map a failure signal back to the plugin that caused it.

Pure decision logic: the daemon gathers what each installed plugin placed on the system (its symlink
destinations, the config sections in those files, baked module names) as `Placement` data, builds an
index from it, and `attribute` takes the jinni's `FailureSignals` (which section / import / file
failed, read from the device log by the JINNI) and names the culprit plugin. No log reading, no
network: the daemon owns only its placement records; reading the device log is the jinni's.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

from protocol import FailureSignals

_CFG_SECTION_HEADER_RE = re.compile(r"^\s*\[([^\]]+)\]", re.MULTILINE)


@dataclass
class Placement:
    """What one installed plugin put on the system: where it symlinked files and which top-level
    Python modules it baked in. The cfg sections are read from the placed files when indexing."""
    plugin_id: str
    destinations: list[str] = field(default_factory=list)
    module_names: list[str] = field(default_factory=list)


@dataclass
class AttributionIndex:
    by_path: dict[str, str]
    by_module: dict[str, str]
    by_section: dict[str, str]

    def plugin_for_section(self, section: str) -> str | None:
        return self.by_section.get(section)

    def placed_section(self, reported_section: str) -> tuple[str, str] | None:
        """The placed section a failure report names, as (declared name, owning plugin). A service
        may report a section in another case than the file declares it, so case is ignored when no
        section matches exactly; an exact match always wins."""
        if reported_section in self.by_section:
            return reported_section, self.by_section[reported_section]
        wanted = reported_section.lower()
        return next(((declared, plugin_id) for declared, plugin_id in self.by_section.items()
                     if declared.lower() == wanted), None)

    def plugin_for_module(self, module: str) -> str | None:
        return self.by_module.get(module)


def _cfg_sections(cfg_path: Path) -> list[str]:
    """The `[section]` headers a placed config file declares (generic INI), so the index knows which
    plugin owns which section. Reading a file the daemon itself placed, not a device log."""
    try:
        text = cfg_path.read_text(errors="replace")
    except OSError:
        return []
    return [header.strip() for header in _CFG_SECTION_HEADER_RE.findall(text)]


def _index_one_destination(destination: str, plugin_id: str, index: AttributionIndex) -> None:
    index.by_path[destination] = plugin_id
    path = Path(destination)
    if path.suffix in (".cfg", ".conf"):
        for section in _cfg_sections(path):
            index.by_section[section] = plugin_id
    elif path.suffix == ".py":
        index.by_module[path.stem] = plugin_id


def build_index(placements: list[Placement]) -> AttributionIndex:
    index = AttributionIndex(by_path={}, by_module={}, by_section={})
    for placement in placements:
        for destination in placement.destinations:
            _index_one_destination(destination, placement.plugin_id, index)
        for module in placement.module_names:
            index.by_module[module] = placement.plugin_id
    return index


def attribute(signals: FailureSignals, index: AttributionIndex) -> tuple[str | None, str]:
    """Name the plugin a jinni-reported failure signal points to, by matching the failing identifier
    (a config section, an import module, a traceback file) against the placement index. Generic: the
    daemon authors no device-specific text and reads no log."""
    placed_sections = (index.placed_section(section) for section in signals.sections)
    failed_section = next(filter(None, placed_sections), None)
    if failed_section is not None:
        declared_section, section_owner = failed_section
        return section_owner, f"the config section [{declared_section}] it placed failed to load"
    for module in signals.modules:
        if module in index.by_module:
            return index.by_module[module], f"the Python import of {module!r} failed"
    for file_path in signals.files:
        if file_path in index.by_path:
            return index.by_path[file_path], f"an error was raised in {file_path}"
    return None, ""
