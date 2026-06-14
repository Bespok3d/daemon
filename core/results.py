"""The result vocabulary shared by every operation: an `item` (one step) and a `phase` (a group of
steps that is ok only if all its items are). Kept as a leaf module so the package executor and the
safety net build identical shapes without depending on each other.
"""
from typing import Any

MAX_OUTPUT_BYTES = 4096


def item(label: str, ok: bool, output: str = "") -> dict[str, Any]:
    return {"label": label, "ok": ok, "output": output}


def phase(phase_id: str, label: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": phase_id, "label": label, "ok": all(it["ok"] for it in items), "items": items}
