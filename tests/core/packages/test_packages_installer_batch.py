# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The batched install entry point (installer_batch.py) settles conflicts between the packages
picked together in one "install selected" call, before any of them is applied: two mutually
exclusive plugins picked in the same call must never both land, and the tie is broken by pick
order, exactly as installing them one at a time would settle it.
"""

from pathlib import Path

from core.packages.batch_refusals import refused_packages


def test_refused_packages_refuses_the_later_pick_of_a_conflicting_pair(tmp_path: Path) -> None:
    display_alpha = {"name": "display-alpha", "conflicts": []}
    display_beta = {"name": "display-beta", "conflicts": ["display-alpha"]}
    picked_in_order = [
        (Path("display-alpha.b3"), display_alpha),
        (Path("display-beta.b3"), display_beta),
    ]

    refused = refused_packages(tmp_path, picked_in_order, already_refused={})

    assert "display-alpha" not in refused
    assert "display-beta" in refused
    assert "display-alpha" in refused["display-beta"]
