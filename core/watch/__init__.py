# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The active watch: the printer reads its live logs, asks its jinni whether a line reports a state
only a power cycle clears, and carries out the user's remedy for it.

Split by concern: `settings` (the user's choice, saved), `kmsg` (reading /dev/kmsg live),
`readers` (which file is read by which reader), `runner` (the reader threads), `remedies` (what
a recognised state leads to), `rebooting` (the states a pending reboot is about to clear) and
`hub` (the live frames to the app).
"""
