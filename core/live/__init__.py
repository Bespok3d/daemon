# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Live state the daemon pushes to the app on change.

Three websocket feeds (`/ws/install-progress`, `/ws/print-state`, `/ws/plugin-log`) each have a
core-side source that lives here: `install_progress` fans an install's phases out to subscribers,
`print_state` parses Moonraker's print_stats into state changes, and `log_capture` tails a plugin's
service log for matches. The route layer owns the sockets; this room owns what flows through them.
Consumers import the submodule they need (`from core.live import print_state`).
"""
