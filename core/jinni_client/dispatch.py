# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The jinni seam's dispatch mechanism (ADR-0037).

Routes one verb to the jinni: in dev the loaded jinni answers in-process (INJECTED by a test, never
imported), once the daemon has spawned its jinni child the call goes over the socket. The typed verb
surface lives in `verbs.py`; this module is the mechanism plus the single injection point a test
overrides (`jinni_client.dispatch.get_jinni`).
"""
from typing import Any

import protocol

from . import transport


def get_jinni() -> Any:
    """The in-process jinni, INJECTED by a test (the daemon never imports the jinni runtime). On the
    printer the socket transport is used and this is never called."""
    raise RuntimeError(
        "no in-process jinni configured: the daemon talks to its jinni over the socket; "
        "a test injects one via jinni_client.dispatch.get_jinni"
    )


def interface_extras(_jinni: Any) -> list[str]:
    """Public names a jinni exposes beyond the standard interface, computed anti-conceal over the
    socket by the jinni's own process; in-process (tests) a test injects the real computation if it
    asserts it, else the standard interface reports none."""
    return []


def route(verb: str, args: list[Any], timeout: float | None = None) -> Any:
    """Route one verb to the jinni. Returns the contract value as Any (a dynamic in-process call or
    a decoded wire frame); each verb in `verbs.py` casts it to its shape at the boundary. `timeout`
    overrides the socket reply timeout for a verb that may block longer than usual."""
    path = transport.socket_path()
    if path is None:
        return getattr(get_jinni(), verb)(*args)
    if timeout is None:
        return protocol.call(path, verb, args)
    return protocol.call(path, verb, args, timeout)
