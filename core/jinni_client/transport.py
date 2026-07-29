# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pluggable transport for the jinni seam (ADR-0037 THE FLIP).

In dev (no device) the loaded jinni answers in-process; on the printer the daemon spawns its jinni
child and every verb routes over the Unix socket. The supervisor throws this switch after the
child's handshake succeeds, and the seam reads it per call. Module-level state because the transport
is process-wide: one daemon, one jinni, one mode at a time.
"""
_active: dict[str, str | None] = {"socket_path": None}


def use_socket(path: str) -> None:
    _active["socket_path"] = path


def use_in_process() -> None:
    _active["socket_path"] = None


def socket_path() -> str | None:
    return _active["socket_path"]
