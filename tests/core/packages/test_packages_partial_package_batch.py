# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A batched update takes a package that leaves out files the same way a single update does: a
left-out file that changed on the printer fails that plugin's update with nothing written."""

from pathlib import Path

import pytest

from core import packages
from core.packages import updater
from core.packages.integrity import MISSING_MEMBER
from tests.core.packages.fake_partial_package import (
    CHANGED,
    KEPT,
    KEPT_BYTES,
    PLUGIN,
    installed,
    partial_package,
)


def test_a_batched_update_leaving_out_a_changed_file_is_refused_with_nothing_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    plugin_dir = installed(tmp_path, b"a binary someone changed")

    results = updater.run_update_batch(tmp_path, {}, [partial_package(tmp_path, "2.0")], {})

    refused = {result["plugin_id"]: result for result in results}[PLUGIN]
    assert refused["ok"] is False
    assert MISSING_MEMBER in refused["reason"]
    assert (plugin_dir / CHANGED).read_text() == "v1.0\n"
    assert (plugin_dir / KEPT).read_bytes() == b"a binary someone changed"


def test_a_batched_update_leaving_out_an_unchanged_file_goes_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(packages, "PLUGIN_ROOT", tmp_path)
    plugin_dir = installed(tmp_path, KEPT_BYTES)

    results = updater.run_update_batch(tmp_path, {}, [partial_package(tmp_path, "2.0")], {})

    assert {result["plugin_id"]: result for result in results}[PLUGIN]["ok"] is True
    assert (plugin_dir / CHANGED).read_text() == "v2.0\n"
    assert (plugin_dir / KEPT).read_bytes() == KEPT_BYTES
