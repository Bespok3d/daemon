# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A diff made near the start or end of a file still fits it after a firmware update grows it.

`diff` cuts a hunk's context short where the file began or ended. GNU and BusyBox patch read the
short side as "this hunk must sit at that end of the file", Apple's patch does not, so the same
package installed on a Mac and was refused in CI and on the printer once the file had grown a line.
"""
from pathlib import Path

import pytest

from core.packages import patch_tool
from core.packages.hunk_context import context_evened

STOCK = "alpha\nbeta\ngamma\ndelta\n"
NEAR_THE_END = (
    "--- a/mod.py\n+++ b/mod.py\n@@ -1,4 +1,4 @@ def mod\n"
    " alpha\n beta\n-gamma\n+gamma2\n delta\n"
)
NEAR_THE_END_EVENED = (
    "--- a/mod.py\n+++ b/mod.py\n@@ -2,3 +2,3 @@ def mod\n"
    " beta\n-gamma\n+gamma2\n delta\n"
)
NEAR_THE_START = (
    "--- a/mod.py\n+++ b/mod.py\n@@ -1,4 +1,4 @@\n"
    " alpha\n-beta\n+beta2\n gamma\n delta\n"
)
NO_NEWLINE_AT_THE_END = (
    "--- a/mod.py\n+++ b/mod.py\n@@ -1,4 +1,4 @@\n"
    " alpha\n-beta\n+beta2\n gamma\n delta\n\\ No newline at end of file\n"
)
NO_NEWLINE_AT_THE_END_EVENED = (
    "--- a/mod.py\n+++ b/mod.py\n@@ -1,3 +1,3 @@\n"
    " alpha\n-beta\n+beta2\n gamma\n"
)
ON_THE_LAST_LINE = (
    "--- a/mod.py\n+++ b/mod.py\n@@ -2,3 +2,3 @@\n"
    " beta\n gamma\n-delta\n+delta2\n"
)
ON_THE_FIRST_LINE = (
    "--- a/mod.py\n+++ b/mod.py\n@@ -1,3 +1,3 @@\n"
    "-alpha\n+alpha0\n beta\n gamma\n"
)
FORM_FEED_LINE = (
    "--- a/mod.py\n+++ b/mod.py\n@@ -1,6 +1,6 @@\n"
    " a\n \x0c\n-c\n+C\n d\n e\n f\n"
)
FORM_FEED_LINE_EVENED = (
    "--- a/mod.py\n+++ b/mod.py\n@@ -1,5 +1,5 @@\n"
    " a\n \x0c\n-c\n+C\n d\n e\n"
)
SYMMETRIC_SECOND_HUNK = "@@ -9,3 +9,3 @@\n six\n-seven\n+seven2\n eight\n"


@pytest.fixture(autouse=True)
def forget_the_patch_already_detected() -> None:
    patch_tool.strictness_flags.cache_clear()


def test_the_longer_context_side_is_trimmed_to_the_shorter() -> None:
    assert context_evened(NEAR_THE_END) == NEAR_THE_END_EVENED


def test_a_no_newline_note_leaves_with_the_line_it_describes() -> None:
    assert context_evened(NO_NEWLINE_AT_THE_END) == NO_NEWLINE_AT_THE_END_EVENED


@pytest.mark.parametrize("fragment_text", [ON_THE_FIRST_LINE, ON_THE_LAST_LINE])
def test_a_hunk_on_the_first_or_last_line_keeps_its_context(fragment_text: str) -> None:
    assert context_evened(fragment_text) == fragment_text


def test_a_crlf_diff_keeps_one_line_ending_on_its_header() -> None:
    crlf = NEAR_THE_END.replace("\n", "\r\n")

    assert context_evened(crlf) == NEAR_THE_END_EVENED.replace("\n", "\r\n")


def test_a_form_feed_inside_a_line_does_not_split_it() -> None:
    assert context_evened(FORM_FEED_LINE) == FORM_FEED_LINE_EVENED


def test_each_hunk_is_evened_on_its_own() -> None:
    two_hunks = NEAR_THE_END + SYMMETRIC_SECOND_HUNK

    assert context_evened(two_hunks) == NEAR_THE_END_EVENED + SYMMETRIC_SECOND_HUNK


def test_a_missing_fragment_does_not_apply(tmp_path: Path) -> None:
    work_path = tmp_path / "mod.py"
    work_path.write_text(STOCK)

    applied = patch_tool.fragment_applies(work_path, tmp_path / "gone.patch", reverse=False)

    assert applied is False
    assert work_path.read_text() == STOCK


@pytest.mark.parametrize(("fragment_text", "grown_file", "patched_file"), [
    (NEAR_THE_END, STOCK + "epsilon\n", "alpha\nbeta\ngamma2\ndelta\nepsilon\n"),
    (NEAR_THE_START, "zero\n" + STOCK, "zero\nalpha\nbeta2\ngamma\ndelta\n"),
])
def test_a_diff_near_one_end_fits_the_file_grown_at_that_end(
    tmp_path: Path, fragment_text: str, grown_file: str, patched_file: str,
) -> None:
    work_path = tmp_path / "mod.py"
    work_path.write_text(grown_file)
    fragment_path = tmp_path / "01-mod.patch"
    fragment_path.write_text(fragment_text)

    assert patch_tool.fragment_applies(work_path, fragment_path, reverse=False) is True
    assert work_path.read_text() == patched_file
