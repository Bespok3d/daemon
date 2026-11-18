# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a recognised state leads to: the user's remedy for its token.

`notify` tells the app. `reboot-when-idle` reboots the printer, but only when nothing is printing;
while a print runs the user is told instead, so the remedy never ends a print. A reboot the app
was already told of that does not happen after all is taken back, and the user is told as for
`notify`: a print started meanwhile, its state could not be read, the printer refused it, the watch
was stopped or changed before it was asked for, or the printer is still up long after accepting it.
A state seen again while its reboot is under way gets no second answer: that reboot is the answer.
"""
import logging
import uuid
from threading import Event, Timer

import protocol

from .. import jinni_client
from . import rebooting
from .hub import ActiveWatchHub
from .settings import RemedyChoice

_log = logging.getLogger(__name__)

REBOOT_NOTICE_GRACE_S = 5
"""How long the reboot frame has to reach the app before the printer goes down."""

REBOOT_DUE_WITHIN_S = 120
"""Past this, a printer that accepted the reboot and is still up has not rebooted."""


def apply_remedy(
    token: str, remedy: RemedyChoice, hub: ActiveWatchHub, stopping: Event,
) -> None:
    """`stopping` is set when the watch stops or its setting changes: a reboot not yet asked for
    is then taken back at once, so the change neither waits for the grace nor reboots anyway. A
    watch already stopping only notifies, so the app never hears of a reboot that cannot happen."""
    if rebooting.is_being_cleared(token):
        return
    if remedy != "reboot-when-idle" or stopping.is_set() or _printer_busy():
        hub.publish({"token": token, "remedy": "notify"})
        return
    _reboot(token, hub, stopping)


def _printer_busy() -> bool:
    """A printer whose state the jinni cannot tell counts as busy: a reboot could end a print."""
    try:
        return bool(jinni_client.blocked_actions())
    except protocol.ProtocolError as error:
        _log.warning("active watch: cannot tell whether the printer is printing: %s", error)
        return True


def _reboot(token: str, hub: ActiveWatchHub, stopping: Event) -> None:
    """The state stops being reported as needing a power cycle before the app hears of the reboot.
    The frames carry one id per reboot, so the app knows which reboot a take-back is about."""
    reboot_id = uuid.uuid4().hex
    rebooting.start_clearing(token)
    try:
        rebooted = _announce_then_reboot(token, reboot_id, hub, stopping)
    except Exception:
        _take_back(token, reboot_id, hub)
        raise
    if not rebooted:
        _take_back(token, reboot_id, hub)
        return
    _take_back_if_still_up(token, reboot_id, hub)


def _announce_then_reboot(
    token: str, reboot_id: str, hub: ActiveWatchHub, stopping: Event,
) -> bool:
    """The printer is checked again after the grace, since a print may start meanwhile."""
    hub.publish({"token": token, "remedy": "reboot", "id": reboot_id})
    if stopping.wait(REBOOT_NOTICE_GRACE_S):
        return False
    return not _printer_busy() and _reboot_accepted()


def _reboot_accepted() -> bool:
    try:
        jinni_client.reboot_printer()
    except protocol.ProtocolError as error:
        _log.warning("active watch: the printer refused the reboot: %s", error)
        return False
    return True


def _take_back_if_still_up(token: str, reboot_id: str, hub: ActiveWatchHub) -> None:
    """A real reboot ends the daemon long before the timer fires. The timer is a daemon thread so
    a daemon stopping for any other reason never waits on it."""
    timer = Timer(REBOOT_DUE_WITHIN_S, _take_back, args=(token, reboot_id, hub))
    timer.daemon = True
    timer.start()


def _take_back(token: str, reboot_id: str, hub: ActiveWatchHub) -> None:
    """The frame names the reboot taken back, so the app drops its notice and asks for a power
    cycle again."""
    rebooting.stop_clearing(token)
    hub.publish({"token": token, "remedy": "notify", "id": reboot_id})
