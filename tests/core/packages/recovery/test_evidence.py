# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""White-box units for post-restart evidence gathering (core/packages/recovery/evidence.py)."""
import json
from pathlib import Path

from core.packages.recovery import evidence


def test_build_attribution_index_indexes_an_extra_module(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugins"
    (plugin_root / "foo-plugin").mkdir(parents=True)
    (plugin_root / "foo-plugin" / "manifest.json").write_text(json.dumps({
        "name": "foo-plugin",
        "version": "0.1.0",
        "files": [],
        "install": {"place": [{"class": "klipper-extra", "src": "files/foo.py"}]},
    }))

    index = evidence._build_attribution_index(
        plugin_root, {"KLIPPER_EXTRAS": "/home/lava/klipper/klippy/extras"}, {}
    )

    assert index.by_module["foo"] == "foo-plugin"
    assert index.by_path["/home/lava/klipper/klippy/extras/foo.py"] == "foo-plugin"
