# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The capabilities this daemon build serves itself, named as services a package can require.

A package says what it needs as a service name, and until now only another plugin could supply one.
A package that hands a patched file over to the daemon needs the daemon to be new enough to take it,
and the daemon is not installed in the plugin root, so no plugin can ever declare that capability on
its behalf. Naming it here is what makes an OLDER daemon refuse such a package at install: it finds
nothing on the printer providing the service and says so, instead of accepting a package it cannot
honour and leaving the user with a plugin that silently does nothing.

A name is added here by the release that starts honouring the capability, and is never removed: a
package on the store keeps requiring it forever.
"""

MIGRATE_PATCH = "migrate-patch"

DAEMON_SERVICES = frozenset({MIGRATE_PATCH})
