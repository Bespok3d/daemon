"""Map a failure signal back to the plugin that caused it.

Pure decision logic: the daemon gathers what each installed plugin placed on the system (its symlink
destinations and baked module names) as `Placement` data, this builds an index from it, and
`attribute_failure` reads a service log to name the culprit. No plugin enumeration, no network - the
daemon (which owns that I/O) feeds the data in, so this stays trivially testable with plain values.
"""
from dataclasses import dataclass, field
from pathlib import Path

from .logs import cfg_sections, failing_config_section, failing_file, failing_import_module


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

    def plugin_for_module(self, module: str) -> str | None:
        return self.by_module.get(module)


def _index_one_destination(destination: str, plugin_id: str, index: AttributionIndex) -> None:
    index.by_path[destination] = plugin_id
    path = Path(destination)
    if path.suffix in (".cfg", ".conf"):
        for section in cfg_sections(path):
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


def attribute_failure(log_text: str, index: AttributionIndex) -> tuple[str | None, str]:
    section = failing_config_section(log_text)
    if section and section in index.by_section:
        return index.by_section[section], f"Klipper config section [{section}] failed to load"
    module = failing_import_module(log_text)
    if module and module in index.by_module:
        return index.by_module[module], f"the Python import of {module!r} failed"
    file_path = failing_file(log_text)
    if file_path and file_path in index.by_path:
        return index.by_path[file_path], f"an error was raised in {file_path}"
    return None, ""
