# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A kmodule's `name` becomes the boot-loader script Bespok3d writes under the plugin's own init.d
directory (`kmodule_script_name` renders `s05<name>`, joined into `plugin_dir/etc/init.d/<script>`
by `write_init_script`). A plugin manifest is untrusted input (see `core/packages/plugin_dir.py`'s
own rule for plugin ids): a `name` carrying a path separator or a `..` segment must never let that
write land outside the plugin's own directory, the same containment every other manifest-driven
write in this repo enforces (`contained_plugin_dir`, `templates.py`, `placement.py`, `members.py`).
"""
from pathlib import Path

import pytest

from core import jinni_client
from core.packages import kmodules
from tests.fakes import FakeKlipperJinni

MP = pytest.MonkeyPatch


class _KmoduleCapableJinni(FakeKlipperJinni):
    def capability_flags(self) -> set[str]:
        return {"overlay", "managed-service", "kernel-modules"}


def _use(jinni: FakeKlipperJinni, monkeypatch: MP) -> None:
    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", lambda: jinni)


def test_generate_module_loaders_refuses_a_module_name_that_escapes_the_plugin_dir(
    tmp_path: Path, monkeypatch: MP
) -> None:
    """A `kmodule.name` of five `..` segments plus a filename cancels `etc/init.d/s05<first
    segment>` exactly back past the plugin directory, so the rendered loader lands in the shared
    plugins root next to every OTHER plugin's own directory rather than staying inside this one."""
    _use(_KmoduleCapableJinni(), monkeypatch)
    plugins_root = tmp_path / "plugins"
    plugin_dir = plugins_root / "tun-module"
    escape_prefix = "/".join([".."] * 5)
    traversal_kmodule = {
        "name": f"{escape_prefix}/escaped-loader",
        "module": "tun.ko",
        "device_nodes": ["/dev/net/tun c 10 200"],
        "autoload": True,
    }

    kmodules.generate_module_loaders([traversal_kmodule], plugin_dir, {})

    escaped_target = plugins_root / "escaped-loader"
    assert not escaped_target.exists(), "loader script escaped the plugin directory"
