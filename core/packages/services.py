"""Services: generate the managed-service init scripts the adapter knows how to write.

A service script is only generated when the printer's jinni advertises managed-service support; the
script body itself comes from the jinni so the daemon names no concrete init format.
"""

from pathlib import Path
from typing import Any

from jinni.loader import get_jinni

from ..intent import SERVICE_SCRIPT_DIR, service_script_name
from ..results import item as _item
from ..results import phase as _phase
from .user_vars import expand


def _expand_service(service: dict, vars: dict[str, str]) -> dict:
    return {
        **service,
        "command": expand(service["command"], vars),
        "args": [expand(arg, vars) for arg in service.get("args", [])],
    }


def _write_one_service_script(service: dict, plugin_dir: Path, vars: dict[str, str], jinni: Any) -> dict:  # noqa: E501
    script_name = service_script_name(service)
    if "managed-service" not in jinni.capability_flags():
        return _item(f"{script_name}: managed services not supported on this printer", ok=False)
    target = plugin_dir / SERVICE_SCRIPT_DIR / script_name
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(jinni.render_service_script(_expand_service(service, vars), vars))
        target.chmod(0o755)
    except Exception as exc:
        return _item(f"{script_name}: {exc}", ok=False)
    return _item(script_name, ok=True)


def generate_service_scripts(services: list[dict], plugin_dir: Path, vars: dict[str, str]) -> dict:
    jinni = get_jinni()
    items = [_write_one_service_script(service, plugin_dir, vars, jinni) for service in services]
    return _phase("services", "Services", items)
