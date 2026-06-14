"""User-variable handling has a canonical home in core.packages.user_vars (validation, the $VAR
expander, persistence to user_vars.json, the per-plugin venv var, and required-variable checks) and
stays reachable from the core.packages namespace, where api.routes, core.selfcheck, and the rest of
the suite reference these as packages.validate_user_vars / packages.expand / load_user_vars."""
from pathlib import Path

import pytest

from core import packages
from core.packages import user_vars


def test_symbols_reexported_from_package_namespace() -> None:
    assert packages.validate_user_vars is user_vars.validate_user_vars
    assert packages.expand is user_vars.expand
    assert packages.load_user_vars is user_vars.load_user_vars


def test_validate_user_vars_accepts_valid_and_rejects_metacharacters() -> None:
    user_vars.validate_user_vars({"SERVER": "192.168.1.50:8000", "TAG": "opt_a@v1.0"})
    user_vars.validate_user_vars({"NOTIFY_EVENTS": "complete,error,cancelled"})
    with pytest.raises(ValueError):
        user_vars.validate_user_vars({"KEY": "value; rm -rf /"})


def test_expand_replaces_longest_key_first() -> None:
    vars = {"BESPOK3D": "/root", "BESPOK3D_KLIPPER": "/root/klipper"}
    assert user_vars.expand("$BESPOK3D_KLIPPER/main.cfg", vars) == "/root/klipper/main.cfg"


def test_persist_and_load_round_trip(tmp_path: Path) -> None:
    user_vars.persist_user_vars(tmp_path, {"SERVER": "10.0.0.1"})
    assert user_vars.load_user_vars(tmp_path) == {"SERVER": "10.0.0.1"}


def test_persist_skips_empty_and_load_defaults_to_empty(tmp_path: Path) -> None:
    user_vars.persist_user_vars(tmp_path, {})
    assert not (tmp_path / "user_vars.json").exists()
    assert user_vars.load_user_vars(tmp_path) == {}


def test_with_plugin_venv_exposes_venv_path() -> None:
    full_vars = user_vars.with_plugin_venv({"BESPOK3D": "/userdata/bespok3d"}, "spoolman")
    assert "PLUGIN_VENV" in full_vars
    assert full_vars["PLUGIN_VENV"].endswith("venv-plugins/spoolman")


def test_missing_required_vars_lists_required_and_absent() -> None:
    manifest = {
        "requires": {
            "variables": [
                {"name": "SERVER", "required": True},
                {"name": "MODE", "required": False},
                {"name": "TOKEN", "required": True},
            ]
        }
    }
    assert user_vars.missing_required_vars(manifest, {"SERVER": "set"}) == ["TOKEN"]
