# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
DAEMON_VERSION = "0.12.24"

# The oldest jinni this daemon will drive. One floor, no ceiling: a jinni newer than this daemon is
# always fine, because the adapter side only ever adds verbs. The daemon publishes this on
# /capabilities so the app can refuse a bad pair before it moves either half, and refuses package
# operations itself so an app that never asked still cannot drive one.
MIN_JINNI_VERSION = "0.1.10"
