# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The made-up printer the patch-handover tests run against: one panel file, plugins that patch it.

Everything here is obviously fake, never a real device path or a real plugin id, and it is shared by
the handover tests so the happy paths and the edge cases describe the same printer."""
import json
from pathlib import Path

from core.packages import patch_handover
from core.packages.baseline import kept_original, stock_copies

PANEL = "/opt/fakeprinter/ui/panel.py"
PANEL_IN_THE_SKIN_DIR = "/opt/fakeprinter/skin/panel.py"
PANEL_NAME = "panel.py"
STOCK_PANEL = "panel start\nrows: 4\ncols: 2\npanel end\n"
TWEAKED_PANEL = "panel start\nrows: 8\ncols: 2\npanel end\n"
ROWS_FRAGMENT = (
    "--- a/panel.py\n+++ b/panel.py\n@@ -1,4 +1,4 @@\n"
    " panel start\n-rows: 4\n+rows: 8\n cols: 2\n panel end\n"
)
COLS_FRAGMENT = (
    "--- a/panel.py\n+++ b/panel.py\n@@ -1,4 +1,4 @@\n"
    " panel start\n rows: 4\n-cols: 2\n+cols: 3\n panel end\n"
)
PANEL_TWEAKS = "panel-tweaks"
BASE_LAYER = "base-layer"


def install_panel_patcher(plugin_root: Path, plugin_id: str, kept_copy: str | None,
                          fragment_text: str = ROWS_FRAGMENT, target: str = PANEL) -> Path:
    """A plugin that declares the panel patch, optionally already holding a copy of the original."""
    plugin_dir = plugin_root / plugin_id
    (plugin_dir / "patches").mkdir(parents=True)
    (plugin_dir / "patches" / "01-panel.patch").write_text(fragment_text)
    (plugin_dir / "manifest.json").write_text(json.dumps({
        "id": plugin_id,
        "install": {"patches": [{"file": target, "patch": "patches/01-panel.patch"}]},
    }))
    if kept_copy is not None:
        stock_copies(plugin_dir).mkdir(parents=True)
        (stock_copies(plugin_dir) / PANEL_NAME).write_text(kept_copy)
    return plugin_dir


def kept_panel(plugin_dir: Path, target: str = PANEL) -> Path:
    """Where this plugin keeps its stock copy of the panel, in whichever layout it holds it."""
    return kept_original(stock_copies(plugin_dir), target)


def hand_over(plugin_root: Path, adopter: Path, target: str = PANEL) -> dict:
    return patch_handover.adopt_patch_ownership(plugin_root, adopter, target, {})
