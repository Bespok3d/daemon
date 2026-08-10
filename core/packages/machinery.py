# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which names are the printer's own machinery, and are therefore never taken off it automatically.

The daemon and the jinni are what make an enrolled printer manageable at all: take either one away
and the owner is left with a printer the app can no longer reach, which is the one outcome the
safety net exists to prevent. Which names those are is a fact this build carries, never a claim a
package makes about itself: a package that could declare itself un-removable could also keep itself
running while it breaks Klipper.

The daemon is named here. The jinni is not installed as a plugin at all (enrollment places it beside
the daemon, outside the plugin root), so it is out of reach of anything that peels a plugin; if a
future path ever installs it as one, it needs a name here too.
"""

DAEMON_PACKAGE = "bespok3d-daemon"

MACHINERY_PACKAGES = frozenset({DAEMON_PACKAGE})


def is_machinery(package_name: str) -> bool:
    """True when the name is part of the printer's own machinery rather than a plugin."""
    return package_name in MACHINERY_PACKAGES
