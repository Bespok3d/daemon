import json
from pathlib import Path

from core import packages
from core.packages import manifest


def test_orchestrator_reexports_manifest_at_for_api_routes() -> None:
    assert packages.manifest_at is manifest.manifest_at


def test_manifest_at_reads_the_plugin_manifest(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "alpha"
    plugin_dir.mkdir()
    (plugin_dir / "manifest.json").write_text(json.dumps({"name": "alpha", "version": "1.0.0"}))
    assert manifest.manifest_at(plugin_dir)["name"] == "alpha"


def test_installed_manifest_dirs_lists_only_manifest_dirs_sorted(tmp_path: Path) -> None:
    for name in ("beta", "alpha"):
        plugin_dir = tmp_path / name
        plugin_dir.mkdir()
        (plugin_dir / "manifest.json").write_text("{}")
    (tmp_path / "loose").mkdir()
    assert [d.name for d in manifest.installed_manifest_dirs(tmp_path)] == ["alpha", "beta"]


def test_installed_manifest_dirs_handles_a_missing_root(tmp_path: Path) -> None:
    assert manifest.installed_manifest_dirs(tmp_path / "nope") == []
