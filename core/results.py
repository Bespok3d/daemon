# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The result vocabulary shared by every operation: an `item` (one step) and a `phase` (a group of
steps that is ok only if all its items are). Kept as a leaf module so the package executor and the
safety net build identical shapes without depending on each other.
"""
from typing import Any

MAX_OUTPUT_BYTES = 4096

# The plugin_id a deferred core-service restart reports under: it is not a plugin, it is the one
# shared restart step a batched op runs at the end. The app localizes this id in its results report.
SERVICES_PLUGIN_ID = "(services)"


def item(label: str, ok: bool, output: str = "") -> dict[str, Any]:
    return {"label": label, "ok": ok, "output": output}


def phase(phase_id: str, label: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": phase_id, "label": label, "ok": all(it["ok"] for it in items), "items": items}
