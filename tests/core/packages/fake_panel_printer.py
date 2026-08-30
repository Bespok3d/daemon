# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The made-up printer the patch-handover tests run against: one panel file, plugins that patch it.

Everything here is obviously fake, never a real device path or a real plugin id, and it is shared by
the handover tests so the happy paths and the edge cases describe the same printer."""
import json
from pathlib import Path

import pytest

from core import jinni_client
from core.packages import installer, patch_handover
from core.packages.baseline import kept_original, stock_copies
from core.packages.deactivation import finalize_install_outcome
from core.packages.manifest import manifest_at
from tests import fake_actuation

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


def settle(plugin_dir: Path) -> None:
    """The install finishing ok, which is the moment the hand-over is committed and the old owners
    let go of the panel's original."""
    patch_handover.commit_patch_handover(plugin_dir, {})


def keep_stock_copy(plugin_dir: Path, target: str, text: str) -> Path:
    """A plugin holding the stock original of one file, kept the way the daemon keeps it now: under
    the file's own path, so the copy says which file on the printer it is a copy of."""
    kept = kept_original(stock_copies(plugin_dir), target)
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text(text)
    return kept


def stop_patching(plugin_dir: Path) -> None:
    """The plugin's next version: the same plugin, no longer declaring the panel patch."""
    manifest = json.loads((plugin_dir / "manifest.json").read_text())
    manifest["install"] = {}
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest))


def read_live_file(path: str) -> str | None:
    """The jinni's read of a device file, on a fake printer whose device tree is a directory."""
    on_the_printer = Path(path)
    return on_the_printer.read_text() if on_the_printer.exists() else None


def patch_the_jinni_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """A jinni that reads and writes each fake printer's files where they really sit, so two
    printers in one test keep their own live panel instead of sharing one."""
    monkeypatch.setattr(jinni_client, "variant_facts", dict)
    monkeypatch.setattr(jinni_client, "fetch", read_live_file)
    monkeypatch.setattr(jinni_client, "write_files", fake_actuation.write_files)


def serve_panel(printer_root: Path, panel_text: str) -> Path:
    """This printer starts serving this panel, and the path it serves it from comes back."""
    live = printer_root / "device" / PANEL_NAME
    live.parent.mkdir(parents=True)
    live.write_text(panel_text)
    return live


def run_install(printer_root: Path, plugin_dir: Path,
                notify: installer.PhaseListener = lambda phase: None) -> list[dict]:
    """This plugin's install, exactly as the daemon runs it for an install and for an update: the
    phases, and then the settle that either commits the hand-over or switches the plugin off."""
    phases, _deferred = installer.apply_install_deferred(
        printer_root, plugin_dir, manifest_at(plugin_dir), {}, notify,
    )
    finalize_install_outcome(plugin_dir, {}, phases)
    return phases
