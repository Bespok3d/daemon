# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The states a reboot started by the watch is about to clear.

Until the printer goes down its jinni still reports them, and an app told both "power cycle it" and
"it is restarting itself" shows two answers to one problem. Kept in memory on purpose: the reboot
that clears the states also forgets this set. A reboot that never happens takes its state out again
(`remedies`), so no state is hidden for good.
"""
clearing: set[str] = set()


def start_clearing(token: str) -> None:
    clearing.add(token)


def stop_clearing(token: str) -> None:
    clearing.discard(token)


def is_being_cleared(token: str) -> bool:
    return token in clearing


def not_being_cleared(tokens: list[str]) -> list[str]:
    return [token for token in tokens if token not in clearing]
