"""Services: generate the managed-service init scripts the adapter knows how to write.

A service script is only generated when the printer's jinni advertises managed-service support; the
script body itself comes from the jinni so the daemon names no concrete init format.
"""

from pathlib import Path

from .. import jinni_client
from ..intent import SERVICE_SCRIPT_DIR, service_script_name
from ..results import item, phase
from .user_vars import expand


def _expand_service(service: dict, vars: dict[str, str]) -> dict:
    return {
        **service,
        "command": expand(service["command"], vars),
        "args": [expand(arg, vars) for arg in service.get("args", [])],
    }


def _write_one_service_script(service: dict, plugin_dir: Path, vars: dict[str, str], flags: set[str]) -> dict:  # noqa: E501
    script_name = service_script_name(service)
    if "managed-service" not in flags:
        return item(f"{script_name}: managed services not supported on this printer", ok=False)
    target = plugin_dir / SERVICE_SCRIPT_DIR / script_name
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(jinni_client.render_service_script(_expand_service(service, vars), vars))
        target.chmod(0o755)
    except Exception as exc:
        return item(f"{script_name}: {exc}", ok=False)
    return item(script_name, ok=True)


def generate_service_scripts(services: list[dict], plugin_dir: Path, vars: dict[str, str]) -> dict:
    flags = jinni_client.capability_flags()
    items = [_write_one_service_script(service, plugin_dir, vars, flags) for service in services]
    return phase("services", "Services", items)
