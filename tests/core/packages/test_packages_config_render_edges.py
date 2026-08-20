# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Edge cases for rendering a plugin's config from user-supplied settings (core.packages.user_vars).

The governing invariant: a config written to the printer must never contain an unfilled
placeholder or a value that breaks the config format, because Klipper refuses to start on a bad
config and the user loses the printer. These cases sit around the existing happy-path coverage in
test_packages_user_vars.py and the existing empty-required-setting fix; they are not a repeat of
either.
"""
import pytest

from core import packages
from core.packages import user_vars


def test_expand_leaves_an_unmatched_placeholder_literal_rather_than_blanking_it() -> None:
    """A template `$NAME` with no matching setting must survive as the literal text (so a
    downstream check can still see and refuse it), never silently disappear into an empty
    string, which would hide a broken config from the check meant to catch it."""
    rendered = user_vars.expand("server=$UNKNOWN_SETTING end", {"OTHER_SETTING": "x"})
    assert rendered == "server=$UNKNOWN_SETTING end"


def test_expand_resolves_a_name_that_is_a_prefix_of_another_name() -> None:
    """SPOOLMAN and SPOOLMAN_PORT must each expand to their own value: substituting the shorter
    name first would splice its value into the middle of the longer name's placeholder."""
    settings = {"SPOOLMAN": "spoolman.local", "SPOOLMAN_PORT": "7912"}
    rendered = user_vars.expand("host=$SPOOLMAN_PORT then $SPOOLMAN", settings)
    assert rendered == "host=7912 then spoolman.local"


def test_validate_user_vars_rejects_an_embedded_newline() -> None:
    """A newline in the middle of a value would split one config line into two, so it must be
    refused before it ever reaches a template."""
    with pytest.raises(ValueError, match="SPOOLMAN_SERVER"):
        user_vars.validate_user_vars({"SPOOLMAN_SERVER": "spoolman.local\nEXTRA=evil"})


def test_validate_user_vars_rejects_a_trailing_newline() -> None:
    """A value ending in a newline still splits the rendered config line in two, exactly like an
    embedded newline; Klipper's line-based parser makes no distinction between the two.

    BROKEN: Python's `$` anchor matches just before a trailing newline as well as at the true end
    of string, so `_SAFE_VAR_RE` accepts a value the printer cannot safely hold."""
    with pytest.raises(ValueError, match="SPOOLMAN_SERVER"):
        user_vars.validate_user_vars({"SPOOLMAN_SERVER": "spoolman.local\n"})


def test_validate_user_vars_rejects_a_dollar_sign_value() -> None:
    """`expand` treats a literal `$` as the start of another placeholder, so a value carrying one
    must be refused rather than silently reinterpreted or left to corrupt a later substitution."""
    with pytest.raises(ValueError, match="TAG"):
        user_vars.validate_user_vars({"TAG": "release$BESPOK3D"})


def test_refuse_missing_settings_rejects_a_whitespace_only_required_value() -> None:
    """A required setting satisfied only by spaces must be refused exactly like an empty one: it
    renders into the config as an effectively blank value while passing a plain truthiness check.

    BROKEN: `missing_required_vars` treats a non-empty string as present without stripping it, so
    a whitespace-only required setting slips past the existing empty-required-setting fix."""
    manifest = {"name": "spoolman", "requires": {"variables": [
        {"name": "SPOOLMAN_SERVER", "required": True},
    ]}}

    with pytest.raises(packages.MissingSettingError):
        user_vars.refuse_missing_settings(manifest, {"SPOOLMAN_SERVER": "   "})
