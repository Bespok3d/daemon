"""Managed-service script generation has a canonical home in core.packages.services and stays
reachable from the core.packages namespace. These guard the not-supported guard a service script
honours before touching the printer and the $VAR expansion of its command and args."""
from pathlib import Path

from core import packages
from core.packages import services


class _NoServiceJinni:
    def capability_flags(self) -> list[str]:
        return []

    def render_service_script(self, service: dict, vars: dict[str, str]) -> str:
        return ""


def test_generate_service_scripts_reexported_from_package_namespace() -> None:
    assert packages.generate_service_scripts is services.generate_service_scripts


def test_expand_service_expands_command_and_args() -> None:
    service = {"name": "feed", "command": "$BIN/run", "args": ["--port", "$PORT"]}
    expanded = services._expand_service(service, {"BIN": "/opt", "PORT": "80"})
    assert expanded["command"] == "/opt/run"
    assert expanded["args"] == ["--port", "80"]
    assert expanded["name"] == "feed"


def test_write_one_service_script_guards_unsupported_printer(tmp_path: Path) -> None:
    item = services._write_one_service_script({"name": "feed"}, tmp_path, {}, _NoServiceJinni())
    assert item["ok"] is False
    assert "managed services not supported" in item["label"]
