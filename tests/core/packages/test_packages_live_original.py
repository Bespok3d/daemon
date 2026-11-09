# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The original of a file two plugins patch, worked out from the file the printer runs now.

One plugin's patch can be written on top of another's: its context holds the other plugin's change.
That patch has to come off first, whatever order the plugins are listed in."""
from pathlib import Path

import pytest

from core.packages.live_original import original_of_the_live_file

STOCK_FILE = "first line\nspeed: 10\nlanes: 2\n"
BOTH_PATCHES_ON = "first line\nspeed: 20\nlanes: 4\n"
PATCH_HEADER = "--- a/file\n+++ b/file\n@@ -1,3 +1,3 @@\n"
SPEED_PATCH = PATCH_HEADER + " first line\n-speed: 10\n+speed: 20\n lanes: 2\n"
# Written on the file with the speed patch on: its context line is the speed patch's change.
LANES_PATCH = PATCH_HEADER + " first line\n speed: 20\n-lanes: 2\n+lanes: 4\n"


def _owner(plugin_root: Path, plugin_id: str, fragment_text: str) -> tuple[Path, list[Path]]:
    plugin_dir = plugin_root / plugin_id
    plugin_dir.mkdir(parents=True)
    fragment = plugin_dir / "01-file.patch"
    fragment.write_text(fragment_text)
    return plugin_dir, [fragment]


@pytest.mark.parametrize("speed_listed_first", [True, False])
def test_a_patch_written_on_another_comes_off_first_whatever_the_order(
    tmp_path: Path, speed_listed_first: bool,
) -> None:
    """Both plugins are on, outside a recovery: each one's patches came off, so both are proven off
    even though the lanes patch alone never fits the original."""
    speed_owner = _owner(tmp_path, "speed-tweak", SPEED_PATCH)
    lanes_owner = _owner(tmp_path, "lanes-tweak", LANES_PATCH)
    listed = [speed_owner, lanes_owner] if speed_listed_first else [lanes_owner, speed_owner]

    original = original_of_the_live_file(BOTH_PATCHES_ON, dict(listed))

    assert original == STOCK_FILE
