"""The daemon's single door to the jinni (ADR-0037).

The daemon is generic: it orchestrates and never names a device or printer service. The device half
is the jinni, and every generic `core/` module reaches it ONLY through this seam, enforced by
`scripts/generic_daemon_guard.py`. The daemon process imports ONLY the protocol; never the jinni
runtime. On the printer the daemon spawns its jinni child (`supervisor.py`) and every verb routes
over the Unix socket; in dev / tests the jinni is INJECTED, not imported.

The seam splits by concern: `dispatch` (the routing mechanism + the `get_jinni` injection point a
test overrides), `verbs` (the typed contract surface), `supervisor` (the jinni child lifecycle), and
`transport` (the in-process-vs-socket switch). This package re-exports them as one facade.
"""
from . import (
    dispatch,  # noqa: F401  exposes jinni_client.dispatch.get_jinni as the test injection point
)
from .actuation import (
    prune_bespok3d_config_dir,
    prune_dead_config_links,
    remove_bespok3d_includes,
    run_actions,
    unwire,
    wire,
    write_files,
)
from .supervisor import default_socket_path, start_jinni, stop_jinni
from .transport import use_in_process, use_socket
from .verbs import (
    blocked_actions,
    capabilities_report,
    capability_flags,
    classify_commands,
    device_node_present,
    fetch,
    health,
    instrument_destination,
    paths,
    placement_destination,
    render_module_script,
    render_service_script,
    restart_command,
    subscribe_blocked_actions,
    variant_facts,
)

__all__ = [
    "default_socket_path", "start_jinni", "stop_jinni", "use_in_process", "use_socket",
    "placement_destination", "instrument_destination", "restart_command", "render_service_script",
    "render_module_script", "device_node_present",
    "capability_flags", "variant_facts", "classify_commands", "paths", "capabilities_report",
    "health", "blocked_actions", "subscribe_blocked_actions", "run_actions", "wire", "unwire",
    "prune_dead_config_links", "remove_bespok3d_includes", "prune_bespok3d_config_dir",
    "fetch", "write_files",
]
