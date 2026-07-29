# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The printer's stable identity: a uuid4 minted once at first daemon startup and persisted in the
data root, so it survives OTA and every computer keys its per-printer state to the same printer.
Reported by GET /status; never regenerated while the identity file holds a value."""

import uuid

from .data_root import DATA_ROOT

IDENTITY_PATH = DATA_ROOT / "etc/daemon/printer_uuid"


def ensure_printer_uuid() -> str:
    existing = stored_printer_uuid()
    if existing is not None:
        return existing
    minted = str(uuid.uuid4())
    IDENTITY_PATH.parent.mkdir(parents=True, exist_ok=True)
    IDENTITY_PATH.write_text(minted)
    return minted


def stored_printer_uuid() -> str | None:
    if not IDENTITY_PATH.exists():
        return None
    return IDENTITY_PATH.read_text().strip() or None
