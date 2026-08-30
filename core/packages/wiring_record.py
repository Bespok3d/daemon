# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the jinni recorded actually writing to the printer's own files, for one plugin.

As it wires, the jinni keeps a declarative undo step per destination path in the plugin's
`wiring.json` (ADR-0037 decision 6). A `restore` step means the jinni wrote that file for this
plugin and kept a stock original to put back; that record, not the plugin's manifest, is the only
honest answer to "did this plugin touch that file". A manifest says what a plugin MEANT to patch,
and an install that failed before its diffs reached the device meant to patch files it never
touched.

The record's shape is the jinni's (`jinni/reversion_record.py`); the names below mirror it, and
`test_wiring_record_shape.py` fails if the two drift apart.
"""

import json
from pathlib import Path

WIRING_RECORD = "wiring.json"
RESTORE_ACTION = "restore"


def _undo_steps(plugin_dir: Path) -> list[dict]:
    record = plugin_dir / WIRING_RECORD
    if not record.is_file():
        return []
    try:
        return list(json.loads(record.read_text()).get("reversions", []))
    except (json.JSONDecodeError, OSError, AttributeError):
        return []


def written_files(plugin_dir: Path) -> set[str]:
    """Every printer-owned file this plugin has actually written and kept an original of."""
    return {str(step["path"]) for step in _undo_steps(plugin_dir)
            if step.get("action") == RESTORE_ACTION and step.get("path")}


def forget_written_file(plugin_dir: Path, target: str) -> None:
    """Drop one file's undo step. Called when another plugin takes the file over: this plugin no
    longer holds its original, so a record still claiming it can be restored from here would send
    the off-host escape hatch to a copy that is gone."""
    record = plugin_dir / WIRING_RECORD
    if not record.is_file():
        return
    kept = [step for step in _undo_steps(plugin_dir) if step.get("path") != target]
    record.write_text(json.dumps({"reversions": kept}, indent=2))
