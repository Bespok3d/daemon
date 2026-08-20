# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The waiting room: access requests a client has made and no authorized client has answered.

Pending file: /userdata/bespok3d/auth/pending.json
  [ { "identity", "label", "public_key", "token", "requested_at" }, ... ]

A request sits here until an already-authorized client grants it (ADR-0016/0008, flat peers),
at which point auth.py moves the client into the ACL. The list is capped: /access/request is
unauthenticated, so an unanswered printer must not accumulate requests without bound.
"""

import json
from datetime import datetime, timezone
from typing import Any

from .data_root import DATA_ROOT

PENDING_PATH = DATA_ROOT / "auth/pending.json"
PENDING_CAP = 8


def load_pending() -> list[dict[str, Any]]:
    """The waiting requests, or none when the file is absent or unreadable. A file torn by a power
    cut mid write must leave the printer taking and answering access requests rather than failing
    every one of them until someone with a shell deletes it; the client simply asks again."""
    if not PENDING_PATH.exists():
        return []
    try:
        stored = json.loads(PENDING_PATH.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    if not isinstance(stored, list):
        return []
    return [entry for entry in stored if isinstance(entry, dict)]


def _save_pending(items: list[dict[str, Any]]) -> None:
    PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    PENDING_PATH.write_text(json.dumps(items, indent=2))


def add_pending(entry: dict[str, Any], cap: int = PENDING_CAP) -> bool:
    """Record an access request. Returns False when the pending list is full (abuse cap)."""
    items = [item for item in load_pending() if item.get("identity") != entry.get("identity")]
    if len(items) >= cap:
        return False
    items.append({**entry, "requested_at": datetime.now(timezone.utc).isoformat()})
    _save_pending(items)
    return True


def list_pending() -> list[dict[str, str]]:
    """Pending requests for display. Never exposes the proposed token."""
    return [
        {"identity": item["identity"], "label": item.get("label", ""),
         "requested_at": item.get("requested_at", "")}
        for item in load_pending()
    ]


def pop_pending(identity: str) -> dict[str, Any] | None:
    items = load_pending()
    match = next((item for item in items if item.get("identity") == identity), None)
    if match is not None:
        _save_pending([item for item in items if item.get("identity") != identity])
    return match
