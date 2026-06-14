"""Regression guard for ADR-0036 packaging: a plugin's root Python-dep declaration must ship in the
`.b3`.

The daemon provisions a per-plugin venv (`requirements.txt`) or symlinks baked packages into the
system site-packages (`klipper_requirements.txt`) only when it finds that file in the unpacked
plugin dir. The packers used to zip just `files/`, `doc/`, and `manifest.json`, so the root-level
declaration was dropped and `_provision_venv` silently skipped: the service init script still
pointed at `venv-plugins/<id>/bin/python3`, which never got created (the status-feed bug).

The packers are sibling-repo shell scripts; this runs each one hermetically (copied into a temp repo
with a fixture plugin) and asserts the declaration lands in the archive. It skips when no sibling
packer is present so the daemon suite still runs standalone.
"""
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from core import packages
from core.packages import python_deps


def _find_workspace_root() -> Path:
    """Walk up to the sibling-repo workspace root (the dir holding `plugins/`), so a test move
    never silently disables the packaging guard the way a hardcoded parent index did."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "plugins").is_dir():
            return parent
    return Path(__file__).resolve().parents[4]


_WORKSPACE_ROOT = _find_workspace_root()
MP = pytest.MonkeyPatch


def _sibling_pack_scripts() -> list[Path]:
    """The co-repo packers that iterate `<plugin-id>/` dirs; a `demo/` fixture exercises them all.

    A bespoke single-plugin packer (u1-hw-camera stages prebuilt binaries from `plugin/`) does not
    fit the fixture, so it is filtered out here.
    """
    found = sorted((_WORKSPACE_ROOT / "plugins").glob("*/scripts/pack.sh"))
    return [script for script in found if 'for dir in "$REPO_DIR"/*/' in script.read_text()]


def _write_fixture_plugin(plugin_dir: Path, declaration: str) -> None:
    (plugin_dir / "files" / "bin").mkdir(parents=True)
    (plugin_dir / "files" / "bin" / "run.py").write_text("print('hi')\n")
    (plugin_dir / declaration).write_text("humanize>=4.9.0\n")
    (plugin_dir / "manifest.json").write_text(
        '{"name": "demo", "version": "0.0.1", "install": {}, "files": []}\n'
    )


@pytest.mark.skipif(not _sibling_pack_scripts(), reason="no sibling plugin packer present")
@pytest.mark.parametrize("declaration", ["requirements.txt", "klipper_requirements.txt"])
@pytest.mark.parametrize("pack_script", _sibling_pack_scripts(), ids=lambda path: path.parts[-3])
def test_packer_ships_root_python_dep_declaration(
    tmp_path: Path, pack_script: Path, declaration: str,
) -> None:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(pack_script, repo / "scripts" / "pack.sh")
    _write_fixture_plugin(repo / "demo", declaration)

    subprocess.run(["sh", "scripts/pack.sh"], cwd=repo, check=True, capture_output=True)

    archive = repo / "dist" / "demo-0.0.1.b3"
    with zipfile.ZipFile(archive) as packed:
        names = packed.namelist()
    assert declaration in names


def _pack_fixture(repo: Path, pack_script: Path, files: dict[str, str]) -> Path:
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(pack_script, repo / "scripts" / "pack.sh")
    for rel, content in files.items():
        path = repo / "demo" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    subprocess.run(["sh", "scripts/pack.sh"], cwd=repo, check=True, capture_output=True)
    return repo / "dist" / "demo-0.0.1.b3"


@pytest.mark.skipif(not _sibling_pack_scripts(), reason="no sibling plugin packer present")
def test_real_b3_provisions_klipper_extra_dep(tmp_path: Path, monkeypatch: MP) -> None:
    """Cross-seam: the REAL packer's .b3 carries klipper_requirements.txt AND the baked package,
    and the REAL daemon links it into the system site-packages on install. This is the join that
    broke for moonraker-notify (apprise declared, never baked, never linked). Per-layer unit tests
    with hand-built fixtures missed it; this exercises packer -> .b3 -> daemon together."""
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path / "plugins")
    monkeypatch.setattr(python_deps, "_already_importable", lambda module: False)
    site_pkgs = tmp_path / "site-packages"
    b3 = _pack_fixture(tmp_path / "repo", _sibling_pack_scripts()[0], {
        "manifest.json": '{"name": "demo", "version": "0.0.1", "install": {}, "files": []}\n',
        "klipper_requirements.txt": "humanize>=4.9.0\n",
        "files/site-packages/humanize/__init__.py": "value = 1\n",
        "files/site-packages/humanize-4.15.0.dist-info/METADATA": "Name: humanize\n",
    })

    packages.install(b3, {"BESPOK3D": str(tmp_path / "b3"), "PYTHON_SITE_PACKAGES": str(site_pkgs)})

    assert (site_pkgs / "humanize").is_symlink()
    assert (site_pkgs / "humanize" / "__init__.py").exists()


def test_bake_deps_targets_printer_architecture() -> None:
    """Guard the arm64 cross-download flags so the bake cannot silently regress to the build
    runner's arch, which shipped x86 wheels that fail to import on the U1's aarch64 interpreter."""
    scripts = sorted((_WORKSPACE_ROOT / "plugins").glob("*/scripts/bake-deps.sh"))
    if not scripts:
        pytest.skip("no bake-deps.sh present")
    for script in scripts:
        text = script.read_text()
        assert "manylinux2014_aarch64" in text
        assert "--only-binary=:all:" in text


def _have(*cmds: str) -> bool:
    return all(shutil.which(cmd) for cmd in cmds)


def test_pack_plugins_never_ships_an_unbakeable_python_plugin(tmp_path: Path) -> None:
    """The monorepo bundler used to only VALIDATE baked deps: a bundled Python plugin with no baked
    artifacts (and no reachable baker) failed its check but the build proceeded and any prior .b3
    stayed in dist, so a broken archive shipped (the moonraker-notify report). The bundler must now
    bake or, when it cannot, drop the stale archive and fail the build. Hermetic: a fixture plugin
    declaring a Python dep, empty artifacts, and no scripts/bake-deps.sh in its tree."""
    packer = _WORKSPACE_ROOT / "Bespok3d" / "scripts" / "pack-plugins.sh"
    if not packer.exists() or not _have("zip", "shasum", "jq", "node"):
        pytest.skip("monorepo packer or its tools not present")

    repo = tmp_path / "Bespok3d"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(packer, repo / "scripts" / "pack-plugins.sh")
    (repo / "scripts" / "bundle.json").write_text('{"bundle": ["widget"]}\n')

    widget = tmp_path / "plugins" / "co" / "widget"
    (widget / "files").mkdir(parents=True)
    (widget / "klipper_requirements.txt").write_text("humanize>=4.9.0\n")
    (widget / "manifest.json").write_text(
        '{"name": "widget", "version": "0.1.0", "install": {}, "files": []}\n'
    )

    dist = repo / "dist" / "plugins"
    dist.mkdir(parents=True)
    stale = dist / "widget-0.1.0.b3"
    stale.write_text("stale archive from a previous build\n")

    result = subprocess.run(
        ["sh", "scripts/pack-plugins.sh"], cwd=repo, capture_output=True, check=False,
    )

    assert result.returncode != 0
    assert not stale.exists()
