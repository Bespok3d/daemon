"""One resolver stands between an outside-supplied plugin id and the filesystem: core/packages/
plugin_dir.py. The daemon runs as root, so each of these tests pins a call site that used to join an
unvalidated id onto a root and then delete or write through it."""

import json
from pathlib import Path

import pytest

from core import python_env
from core.packages import batch_uninstaller, plugin_venv, reconfigurer, uninstaller, user_vars
from core.packages.integrity import ESCAPING_PLUGIN_ID, IntegrityError
from core.packages.plugin_dir import contained_plugin_dir

ESCAPING_IDS = ["..", ".", "../etc", "nested/id", "/absolute", ""]


def _install_manifest(plugin_root: Path, plugin_id: str) -> None:
    plugin_dir = plugin_root / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(json.dumps({"name": plugin_id, "install": {}}))


def test_a_plain_id_resolves_to_its_directory_under_the_root(tmp_path: Path) -> None:
    assert contained_plugin_dir(tmp_path, "spoolman") == tmp_path / "spoolman"


@pytest.mark.parametrize("plugin_id", ESCAPING_IDS)
def test_an_id_naming_anything_but_its_own_directory_is_refused(
    tmp_path: Path, plugin_id: str,
) -> None:
    with pytest.raises(IntegrityError) as refusal:
        contained_plugin_dir(tmp_path, plugin_id)

    assert refusal.value.reason == ESCAPING_PLUGIN_ID


def test_uninstall_refuses_an_escaping_id_and_leaves_the_plugin_root_whole(
    tmp_path: Path,
) -> None:
    plugin_root = tmp_path / "plugins"
    _install_manifest(plugin_root, "spoolman")

    with pytest.raises(IntegrityError) as refusal:
        uninstaller.run_uninstall(plugin_root, "..", {})

    assert refusal.value.reason == ESCAPING_PLUGIN_ID
    assert (plugin_root / "spoolman").is_dir()


def test_the_removal_walk_refuses_an_escaping_id_before_it_deletes(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugins"
    _install_manifest(plugin_root, "spoolman")

    with pytest.raises(IntegrityError):
        uninstaller.remove_with_dependents(plugin_root, "..", {}, [])

    assert (plugin_root / "spoolman").is_dir()


def test_batched_uninstall_refuses_an_escaping_id_in_the_selection(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugins"
    _install_manifest(plugin_root, "spoolman")

    with pytest.raises(IntegrityError) as refusal:
        batch_uninstaller.run_uninstall_batch(plugin_root, ["spoolman", ".."], {})

    assert refusal.value.reason == ESCAPING_PLUGIN_ID
    assert (plugin_root / "spoolman").is_dir()


def test_reconfigure_refuses_an_escaping_id_before_rendering_or_chowning(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugins"
    _install_manifest(plugin_root, "spoolman")

    with pytest.raises(IntegrityError) as refusal:
        reconfigurer.run_reconfigure(plugin_root, "..", {}, {})

    assert refusal.value.reason == ESCAPING_PLUGIN_ID


def test_venv_removal_refuses_an_escaping_id_and_spares_the_bespok3d_root(
    tmp_path: Path,
) -> None:
    bespok3d_root = tmp_path / "bespok3d"
    python_env.plugin_venv_root(str(bespok3d_root)).mkdir(parents=True)

    with pytest.raises(IntegrityError) as refusal:
        plugin_venv.remove_plugin_venv("..", {"BESPOK3D": str(bespok3d_root)})

    assert refusal.value.reason == ESCAPING_PLUGIN_ID
    assert bespok3d_root.is_dir()


def test_the_plugin_venv_var_refuses_an_escaping_id_before_reaching_a_service_command(
    tmp_path: Path,
) -> None:
    """$PLUGIN_VENV is expanded into commands the printer runs as root, so an id naming anything but
    its own directory must never reach one."""
    with pytest.raises(IntegrityError) as refusal:
        user_vars.with_plugin_venv({"BESPOK3D": str(tmp_path)}, "../../usr")

    assert refusal.value.reason == ESCAPING_PLUGIN_ID
