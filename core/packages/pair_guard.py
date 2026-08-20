# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The pair guard: refuse a plugin op when this daemon and this printer's jinni do not fit together.

The compatibility contract is two floors and no ceilings, and this daemon holds both of them.

A package declares the oldest daemon it will run against (`min_daemon_version`). The app checks that
before it sends the package, and the printer checks it again here: the app is not always the one
deciding (a sideloaded package, an older app, a package built after the app shipped), and a package
that reaches a daemon too old for it would otherwise install and quietly do nothing.

This daemon declares the oldest jinni it will drive (`MIN_JINNI_VERSION`), publishes it on
/capabilities, and enforces it here, so an app that never read the declaration still cannot drive a
bad pair.

Only a pair the daemon can PROVE is bad is refused. A jinni that reports no readable version is a
question the daemon could not ask, not a bad pair, and refusing on it would take a working printer
away from its owner over an unanswered question.
"""

from version import DAEMON_VERSION, MIN_JINNI_VERSION

from .. import jinni_client
from ..versions import known_to_be_below
from .errors import IncompatiblePairError

JINNI_SIDE = "jinni"
DAEMON_SIDE = "daemon"


def running_jinni_version() -> str:
    """What the jinni on this printer says it is, or 'unknown' from a jinni too old to say."""
    return str(jinni_client.capabilities_report().get("jinni_version", "unknown"))


def guard_compatible_pair() -> None:
    """Refuse a plugin op when this printer's jinni is older than this daemon will drive."""
    running = running_jinni_version()
    if known_to_be_below(running, MIN_JINNI_VERSION):
        raise IncompatiblePairError(JINNI_SIDE, MIN_JINNI_VERSION, running)


def guard_daemon_reaches_the_package_floor(manifest: dict) -> None:
    """Refuse a package that asks for a newer daemon than this printer runs, before any of it is
    written. Only a floor this daemon can PROVE it is under is refused: a floor that is not a
    readable version is a question that could not be asked, not a package that is proven wrong."""
    declared_floor = str(manifest.get("min_daemon_version") or "")
    if declared_floor and known_to_be_below(DAEMON_VERSION, declared_floor):
        raise IncompatiblePairError(DAEMON_SIDE, declared_floor, DAEMON_VERSION)
