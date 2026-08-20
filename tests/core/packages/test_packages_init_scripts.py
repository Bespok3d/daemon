# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The init-script write mechanic shared by the managed-service and kernel-module loaders: it
must refuse a missing script name rather than write the boot script over the plugin's init.d
directory."""
from pathlib import Path

from core.packages.init_scripts import write_init_script


def test_write_init_script_refuses_an_empty_script_name(tmp_path: Path) -> None:
    """`plugin_dir / "etc/init.d" / script_name` collapses to the init.d directory itself when
    script_name is empty (pathlib drops an empty path segment on join), so writing the rendered
    script there replaces the directory the boot runner iterates with a plain file. A script name
    that resolves empty must be refused before any write, not silently accepted."""
    plugin_dir = tmp_path / "empty-name-plugin"

    result = write_init_script(plugin_dir, "", lambda: "#!/bin/sh\necho boot\n")

    init_scripts_dir = plugin_dir / "etc" / "init.d"
    assert result["ok"] is False
    assert not init_scripts_dir.is_file()
