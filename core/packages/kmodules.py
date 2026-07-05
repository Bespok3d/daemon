"""Kernel modules: generate the loader scripts the adapter knows how to write, and run the load.

A plugin that ships a `.ko` places it (the `kernel-module` destination class) and declares an
`install.kmodule` entry: the module, the device nodes it needs (`/dev/net/tun c 10 200`), and
whether to load it now. The daemon asks the jinni to render a boot loader script (it owns
insmod/mknod/rmmod, ADR-0037), gates the whole feature on the printer's `kernel-modules` capability,
and drops the script under the plugin's init.d for `autostart.kmodule_ops` to wire as an s05 link.

Loading runs immediately in its own phase (`load_modules`), never through the deferred core-service
restart batch: a kernel module load restarts no core service, and it must precede any service that
needs it. A load that fails reports `ok=False`, so the install safety net deactivates the plugin and
the printer is never left with a half-loaded module.
"""

from pathlib import Path

from .. import jinni_client
from ..autostart import kmodule_script_name
from ..results import item, phase
from .init_scripts import write_init_script
from .user_vars import expand

_CAPABILITY_FLAG = "kernel-modules"


def _write_one_loader(kmodule: dict, plugin_dir: Path, vars: dict[str, str], flags: set[str]) -> dict:  # noqa: E501
    script_name = kmodule_script_name(kmodule)
    if _CAPABILITY_FLAG not in flags:
        return item(f"{script_name}: kernel modules not supported on this printer", ok=False)
    return write_init_script(
        plugin_dir, script_name, lambda: jinni_client.render_module_script(kmodule, vars)
    )


def generate_module_loaders(kmodules: list[dict], plugin_dir: Path, vars: dict[str, str]) -> dict:
    if not kmodules:
        return phase("kmodules", "Kernel module loaders", [])
    flags = jinni_client.capability_flags()
    items = [_write_one_loader(kmodule, plugin_dir, vars, flags) for kmodule in kmodules]
    return phase("kmodules", "Kernel module loaders", items)


def load_modules(loads: list[str], vars: dict[str, str]) -> dict:
    """Run each module-load command now (the jinni mknods the device nodes and insmods the module).
    Immediate, not deferred: a module must be loaded before the services that depend on it."""
    expanded = [expand(command, vars) for command in loads]
    results = jinni_client.run_actions(expanded)
    items = [item(command, ok=result.ok, output=result.output)
             for command, result in zip(expanded, results)]
    return phase("kmodule-load", "Load kernel modules", items)
