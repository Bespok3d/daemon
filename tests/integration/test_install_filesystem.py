# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""In-vitro daemon integration: install a real .b3 into a temp workspace and assert the actual
filesystem effect (extraction, symlinks, dirs), plus the selfcheck-drift and recover round-trips.

These exercise the multi-step install machinery (unpack -> dirs -> templates -> symlinks -> patches)
end to end against a real directory tree, with no device and no services: every plugin here declares
`start: []`, so nothing touches Klipper/Moonraker. The printer remains the judge of device fidelity;
this is the logical-coherence net below it.
"""
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from core import packages
from core.packages.integrity import ESCAPING_MEMBER, UNDECLARED_MEMBER, IntegrityError
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


def test_signed_package_installs_its_payload_clean(workspace: Path) -> None:
    klipper = workspace / "klipper"
    klipper.mkdir()
    members = {"files/x.cfg": "DATA", "manifest.json.sig": "-----BEGIN PGP SIGNATURE-----"}
    package_path = build_b3(workspace, "demo", config_symlink_install(), members)

    packages.install(package_path, {"BESPOK3D_KLIPPER": str(klipper)})

    link = klipper / "x.cfg"
    assert link.is_symlink()
    assert link.read_text() == "DATA"


def hand_packed_b3(
    base: Path, name: str, manifest_files: list[dict], members: dict[str, str],
) -> Path:
    """A .b3 whose files[] the caller declares directly, diverging from `members` on purpose: the
    tamper cases need a manifest and an archive that disagree, which `package_bytes` refuses to
    build."""
    empty_install: dict[str, list] = {"dirs": [], "symlinks": [], "patches": []}
    manifest = {"name": name, "version": "1.0.0", "install": empty_install, "files": manifest_files}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for member_name, content in members.items():
            archive.writestr(member_name, content)
    package_path = base / f"{name}.b3"
    package_path.write_bytes(buffer.getvalue())
    return package_path


def test_install_refuses_an_undeclared_member_and_installs_nothing(workspace: Path) -> None:
    plugin_root = workspace / "plugins"
    declared = [{"path": "files/x.cfg", "sha256": "irrelevant", "mode": "644"}]
    members = {"files/x.cfg": "DATA", "files/smuggled.cfg": "UNSIGNED"}
    package_path = hand_packed_b3(workspace, "demo", declared, members)

    with pytest.raises(IntegrityError) as caught:
        packages.install(package_path, {})

    assert caught.value.reason == UNDECLARED_MEMBER
    assert not (plugin_root / "demo").exists()


def test_install_refuses_an_escaping_member_and_writes_no_payload(workspace: Path) -> None:
    plugin_root = workspace / "plugins"
    traversal = "../victim.cfg"
    declared = [{"path": traversal, "sha256": "irrelevant", "mode": "644"}]
    members = {traversal: "CLOBBERED"}
    package_path = hand_packed_b3(workspace, "demo", declared, members)

    with pytest.raises(IntegrityError) as caught:
        packages.install(package_path, {})

    assert caught.value.reason == ESCAPING_MEMBER
    assert not (workspace / "victim.cfg").exists()
    assert not (plugin_root / "demo").exists()


def test_refused_escaping_reinstall_keeps_the_existing_install(workspace: Path) -> None:
    # A tampered reinstall over a working plugin must not take the good install down with it: the
    # escaping refusal fires before the plugin dir is touched, so the payload already on disk stays.
    klipper = workspace / "klipper"
    klipper.mkdir()
    vars = {"BESPOK3D_KLIPPER": str(klipper)}
    plugin_root = workspace / "plugins"
    good = build_b3(workspace, "demo", config_symlink_install(), {"files/x.cfg": "DATA"})
    packages.install(good, vars)
    assert (plugin_root / "demo" / "files" / "x.cfg").read_text() == "DATA"

    traversal = "../victim.cfg"
    declared = [{"path": traversal, "sha256": "irrelevant", "mode": "644"}]
    tampered = hand_packed_b3(workspace, "demo", declared, {traversal: "CLOBBERED"})
    with pytest.raises(IntegrityError) as caught:
        packages.install(tampered, vars)

    assert caught.value.reason == ESCAPING_MEMBER
    assert (plugin_root / "demo" / "files" / "x.cfg").read_text() == "DATA"


def test_install_refuses_a_manifest_path_that_escapes_the_plugin_dir(workspace: Path) -> None:
    # The archive is clean (its one member is declared and contained), but the manifest files[]
    # also names a doc-prefixed path climbing out of the plugin dir. apply_modes chmods manifest
    # paths as root, and installed_files drops doc entries so verify_files never sees this one, so
    # without the containment check on files[] the install would chmod a file outside the sandbox.
    # It is refused before the plugin dir is touched, and the file outside is left as it was.
    plugin_root = workspace / "plugins"
    victim = workspace / "victim.cfg"
    victim.write_text("STOCK")
    victim.chmod(0o644)
    escaping = "doc/../../../victim.cfg"
    good_hash = hashlib.sha256(b"DATA").hexdigest()
    declared = [
        {"path": "files/x.cfg", "sha256": good_hash, "mode": "644"},
        {"path": escaping, "mode": "4777"},
    ]
    package_path = hand_packed_b3(workspace, "demo", declared, {"files/x.cfg": "DATA"})

    with pytest.raises(IntegrityError) as caught:
        packages.install(package_path, {})

    assert caught.value.reason == ESCAPING_MEMBER
    assert not (plugin_root / "demo").exists()
    assert victim.stat().st_mode & 0o7777 == 0o644


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
