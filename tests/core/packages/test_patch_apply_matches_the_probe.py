# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A diff the printer proved fits is applied under the rules it was proved under.

The daemon asks `patch` twice about the same fragment: once to prove the file it is about to touch
is these diffs' original, and once to actually apply it. Asking the two questions under different
rules is how a printer refuses a package it has just proved fits. It happened: the apply asked
BusyBox patch to skip an already applied hunk, BusyBox read a plain addition at the end of the file
as a reversed patch, and two base packages would not install on a printer whose files they fitted.
"""
import subprocess

import pytest

from tests.core.packages.fake_panel_printer import (
    BASE_LAYER,
    COLS_FRAGMENT,
    PANEL_TWEAKS,
    ROWS_FRAGMENT,
    STOCK_PANEL,
    TWEAKED_PANEL,
    install_panel_patcher,
    keep_stock_copy,
    patch_the_jinni_in,
    run_install,
    serve_panel,
)

SKIP_AN_APPLIED_HUNK = "-N"
A_FRAGMENT_RUN = "--strip=1"


@pytest.fixture(autouse=True)
def jinni(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_the_jinni_in(monkeypatch)


def _record_every_patch_run(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Every command line the daemon hands the machine's patch program to put one fragment on one
    file, while still running it. Asking the program which patch it is does not name a fragment and
    is not one of them."""
    asked: list[list[str]] = []
    really_run = subprocess.run

    def record_then_run(command: list[str], *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if command and command[0] == "patch" and A_FRAGMENT_RUN in command:
            asked.append(list(command))
        return really_run(command, *args, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(subprocess, "run", record_then_run)
    return asked


def _rules_asked_for(command: list[str]) -> tuple[str, ...]:
    """The rules this command puts on patch, with the direction left out: applying a fragment and
    reversing one are the same question asked forwards and backwards."""
    return tuple(word for word in command if word.startswith("-") and word != "-R")


def test_a_fragment_is_applied_under_the_rules_it_was_proved_under(
    tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The base layer takes a panel over from a plugin, which makes the daemon both prove and apply.
    Every question it asks patch about that panel puts the same rules on it, and none of them asks
    patch to skip a hunk it thinks is already applied."""
    printer_root = tmp_path / "printer"  # type: ignore[operator]
    live_panel = serve_panel(printer_root, TWEAKED_PANEL)
    patcher = install_panel_patcher(printer_root, PANEL_TWEAKS, kept_copy=None,
                                    fragment_text=ROWS_FRAGMENT, target=str(live_panel))
    keep_stock_copy(patcher, str(live_panel), STOCK_PANEL)
    base_layer = install_panel_patcher(printer_root, BASE_LAYER, kept_copy=None,
                                       fragment_text=COLS_FRAGMENT, target=str(live_panel))
    asked = _record_every_patch_run(monkeypatch)

    phases = run_install(printer_root, base_layer)

    assert all(finished["ok"] for finished in phases)
    assert len(asked) > 1
    assert not [command for command in asked if SKIP_AN_APPLIED_HUNK in command]
    assert len({_rules_asked_for(command) for command in asked}) == 1
