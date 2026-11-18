# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
import os
from pathlib import Path

import pytest

from core.json_file import read_json, write_json


def test_a_written_value_reads_back(tmp_path: Path) -> None:
    state_file = tmp_path / "etc/state.json"
    write_json(state_file, {"enabled": True})
    assert read_json(state_file) == {"enabled": True}


def test_a_torn_file_reads_as_nothing(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    state_file.write_text('{"enabled": tr')
    assert read_json(state_file) is None


def test_a_missing_file_reads_as_nothing(tmp_path: Path) -> None:
    assert read_json(tmp_path / "absent.json") is None


def test_a_rewrite_replaces_the_file_and_leaves_no_staging_copy(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    write_json(state_file, {"enabled": True})
    write_json(state_file, {"enabled": False})
    assert read_json(state_file) == {"enabled": False}
    assert [entry.name for entry in tmp_path.iterdir()] == ["state.json"]


def test_a_value_that_is_not_json_leaves_the_file_as_it_was(tmp_path: Path) -> None:
    state_file = tmp_path / "state.json"
    write_json(state_file, {"enabled": True})
    with pytest.raises(TypeError):
        write_json(state_file, {"enabled": object()})
    assert read_json(state_file) == {"enabled": True}
    assert [entry.name for entry in tmp_path.iterdir()] == ["state.json"]


def refuse_to_rename(staging: Path, target: Path) -> None:
    raise OSError(28, "No space left on device")


def test_a_failed_write_leaves_the_old_file_and_no_staging_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_file = tmp_path / "state.json"
    write_json(state_file, {"enabled": True})
    monkeypatch.setattr(os, "replace", refuse_to_rename)
    with pytest.raises(OSError, match="No space left"):
        write_json(state_file, {"enabled": False})
    assert read_json(state_file) == {"enabled": True}
    assert [entry.name for entry in tmp_path.iterdir()] == ["state.json"]
