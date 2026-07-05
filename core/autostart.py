"""Wire a generated boot script (a managed service, a kernel-module loader) into the autostart dir.

A managed service (ADR-0026/0029) and a kernel-module loader (ADR-0039) are each realized by the
adapter generating an init script the daemon writes under the plugin's `etc/init.d` and wires into
the autostart dir. The script CONTENT is the adapter's HOW; the wiring here is core vocabulary over
the daemon's own $BESPOK3D tree, so it names no device value and stays in core. A service takes an
s65 prefix; a module loader takes s05 so it loads BEFORE the services. The daemon drives both with
`restart` (unload/stop then load/start), so an update shipping a changed script or `.ko` reloads at
once, not after a reboot; the boot runner still drives them with plain `start`. `intent.py` folds
the produced symlinks/starts/stops in.
"""
from collections.abc import Callable

SERVICE_SCRIPT_DIR = "etc/init.d"
SERVICE_AUTOSTART_DEST = "$BESPOK3D/etc/init.d/autostart/{script}"


def service_script_name(service: dict) -> str:
    return f"s65{service['name']}"


def kmodule_script_name(kmodule: dict) -> str:
    """A kernel-module loader takes an s05 prefix so S99bespok3d loads it BEFORE the s65 services
    (the boot runner starts the autostart dir sorted ascending): a service that needs the module
    finds it already loaded."""
    return f"s05{kmodule['name']}"


def _autostart_ops(script: str, active: bool) -> tuple[dict, str | None, str]:
    """Return (autostart_symlink, start_command_or_None, stop_command) for one boot script.

    Shared by managed services and kernel-module loaders. The script content is the adapter's, so
    here we only wire it into the autostart dir and hook start/stop. The start hook uses `restart`
    (not `start`) so a re-apply reloads the changed script or module in place."""
    source = f"{SERVICE_SCRIPT_DIR}/{script}"
    destination = SERVICE_AUTOSTART_DEST.format(script=script)
    symlink = {"from": source, "to": destination}
    start = f"{destination} restart" if active else None
    return symlink, start, f"{destination} stop"


def service_ops(service: dict) -> tuple[dict, str | None, str]:
    return _autostart_ops(service_script_name(service), bool(service.get("autostart")))


def kmodule_ops(kmodule: dict) -> tuple[dict, str | None, str]:
    return _autostart_ops(kmodule_script_name(kmodule), bool(kmodule.get("autoload")))


def autostart_additions(
    entries: list[dict], ops: Callable[[dict], tuple[dict, str | None, str]]
) -> tuple[list[dict], list[str], list[str]]:
    """Collect one autostart family's (symlinks, start_commands, stop_commands): every entry wires a
    symlink and a stop, and an active one adds a start."""
    symlinks: list[dict] = []
    starts: list[str] = []
    stops: list[str] = []
    for entry in entries:
        symlink_op, start_cmd, stop_cmd = ops(entry)
        symlinks.append(symlink_op)
        if start_cmd is not None:
            starts.append(start_cmd)
        stops.append(stop_cmd)
    return symlinks, starts, stops
