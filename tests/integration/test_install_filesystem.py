"""In-vitro daemon integration: install a real .b3 into a temp workspace and assert the actual
filesystem effect (extraction, symlinks, dirs), plus the selfcheck-drift and recover round-trips.

These exercise the multi-step install machinery (unpack -> dirs -> templates -> symlinks -> patches)
end to end against a real directory tree, with no device and no services: every plugin here declares
`start: []`, so nothing touches Klipper/Moonraker. The printer remains the judge of device fidelity;
this is the logical-coherence net below it.
"""
from pathlib import Path

import pytest

from core import packages
from core.packages.signatures import plugins_with_stored_signature
from core.selfcheck import run_selfcheck
from tests.package_fixtures import package_bytes

MP = pytest.MonkeyPatch


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: MP) -> Path:
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    monkeypatch.setattr(packages, "PLUGIN_ROOT", plugin_root)
    return tmp_path


def build_b3(base: Path, name: str, install: dict, files: dict[str, str]) -> Path:
    manifest = {"name": name, "version": "1.0.0", "install": install}
    package_path = base / f"{name}.b3"
    package_path.write_bytes(package_bytes(manifest, files))
    return package_path


def config_symlink_install() -> dict:
    return {
        "dirs": [],
        "symlinks": [{"from": "files/x.cfg", "to": "$BESPOK3D_KLIPPER/x.cfg"}],
        "patches": [],
    }


def test_install_symlinks_the_config_into_its_destination(workspace: Path) -> None:
    klipper = workspace / "klipper"
    klipper.mkdir()
    package_path = build_b3(workspace, "demo", config_symlink_install(), {"files/x.cfg": "DATA"})

    packages.install(package_path, {"BESPOK3D_KLIPPER": str(klipper)})

    link = klipper / "x.cfg"
    assert link.is_symlink()
    assert link.read_text() == "DATA"


def test_install_creates_declared_directories(workspace: Path) -> None:
    klipper = workspace / "klipper"
    klipper.mkdir()
    install = {"dirs": ["$BESPOK3D_KLIPPER/sub"], "symlinks": [], "patches": []}
    package_path = build_b3(workspace, "demo", install, {})

    packages.install(package_path, {"BESPOK3D_KLIPPER": str(klipper)})

    assert (klipper / "sub").is_dir()


def test_selfcheck_reports_drift_when_a_symlink_is_removed(workspace: Path) -> None:
    klipper = workspace / "klipper"
    klipper.mkdir()
    vars = {"BESPOK3D_KLIPPER": str(klipper)}
    package_path = build_b3(workspace, "demo", config_symlink_install(), {"files/x.cfg": "DATA"})
    packages.install(package_path, vars)

    assert run_selfcheck(vars) == []

    (klipper / "x.cfg").unlink()
    drift = run_selfcheck(vars)
    assert len(drift) == 1
    assert drift[0]["plugin_id"] == "demo"
    assert drift[0]["symlink_issues"]


def test_recover_reapplies_a_removed_symlink(workspace: Path) -> None:
    klipper = workspace / "klipper"
    klipper.mkdir()
    vars = {"BESPOK3D_KLIPPER": str(klipper)}
    package_path = build_b3(workspace, "demo", config_symlink_install(), {"files/x.cfg": "DATA"})
    packages.install(package_path, vars)

    (klipper / "x.cfg").unlink()
    packages.recover(vars)

    assert (klipper / "x.cfg").is_symlink()


def test_the_shipped_signature_survives_install_and_recover(workspace: Path) -> None:
    # The detached signature is kept on disk so a package installed while the GPG leg was waived can
    # still be checked against a key later. Recover re-applies an install, so it must not lose it.
    klipper = workspace / "klipper"
    klipper.mkdir()
    vars = {"BESPOK3D_KLIPPER": str(klipper)}
    members = {"files/x.cfg": "DATA", "manifest.json.sig": "-----BEGIN PGP SIGNATURE-----"}
    package_path = build_b3(workspace, "demo", config_symlink_install(), members)
    plugin_root = workspace / "plugins"

    packages.install(package_path, vars)
    assert plugins_with_stored_signature(plugin_root) == ["demo"]

    packages.recover(vars)
    assert (plugin_root / "demo" / "manifest.json.sig").read_text().startswith("-----BEGIN PGP")
    assert plugins_with_stored_signature(plugin_root) == ["demo"]
