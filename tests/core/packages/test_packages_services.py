"""Managed-service script generation has a canonical home in core.packages.services. These guard the
not-supported guard a service script honours before touching the printer and the $VAR expansion of
its command and args."""
from pathlib import Path

from core.packages import services


def test_expand_service_expands_command_and_args() -> None:
    service = {"name": "feed", "command": "$BIN/run", "args": ["--port", "$PORT"]}
    expanded = services._expand_service(service, {"BIN": "/opt", "PORT": "80"})
    assert expanded["command"] == "/opt/run"
    assert expanded["args"] == ["--port", "80"]
    assert expanded["name"] == "feed"


def test_write_one_service_script_guards_unsupported_printer(tmp_path: Path) -> None:
    item = services._write_one_service_script({"name": "feed"}, tmp_path, {}, flags=set())
    assert item["ok"] is False
    assert "managed services not supported" in item["label"]
