# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which baked wheels a plugin venv no longer holds intact, read from pip's RECORD.

pip skips a wheel whose name and version are already installed, so without this a file torn by a
power cut stays torn on every later install, update and recover.
"""
import os
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from core.packages.venv_health import broken_wheels
from tests.core.packages.fake_plugin_venv import (
    HUMANIZE_DIST_INFO,
    HUMANIZE_WHEEL,
    SITE_PACKAGES,
    YAML_WHEEL,
    healthy_venv,
    install_distribution,
    recorded_digest,
)


def _wheels(tmp_path: Path) -> list[Path]:
    return [tmp_path / "wheels" / HUMANIZE_WHEEL, tmp_path / "wheels" / YAML_WHEEL]


def test_an_intact_venv_has_no_broken_wheel(tmp_path: Path) -> None:
    assert broken_wheels(healthy_venv(tmp_path), _wheels(tmp_path)) == []


@pytest.mark.parametrize(
    "tear",
    [
        lambda site: (site / "humanize/__init__.py").write_bytes(b""),
        lambda site: (site / "humanize/__init__.py").unlink(),
        lambda site: (site / "../../../bin/humanize").unlink(),
        lambda site: (site / HUMANIZE_DIST_INFO / "RECORD").unlink(),
        lambda site: (site / HUMANIZE_DIST_INFO / "RECORD").write_bytes(b"\xff\xfe torn"),
        lambda site: (site / HUMANIZE_DIST_INFO / "RECORD").write_text(""),
        lambda site: shutil.rmtree(site / HUMANIZE_DIST_INFO),
    ],
    ids=["changed", "missing", "missing-script", "no-record", "unreadable-record", "empty-record",
         "no-dist-info"],
)
def test_a_torn_distribution_marks_only_its_own_wheel(
    tmp_path: Path, tear: Callable[[Path], object],
) -> None:
    venv_path = healthy_venv(tmp_path)
    tear(venv_path / SITE_PACKAGES)

    assert broken_wheels(venv_path, _wheels(tmp_path)) == [tmp_path / "wheels" / HUMANIZE_WHEEL]


def test_a_row_in_an_algorithm_that_cannot_be_checked_is_skipped(tmp_path: Path) -> None:
    venv_path = tmp_path / "venv"
    site_packages = install_distribution(venv_path, HUMANIZE_DIST_INFO, {})
    (site_packages / HUMANIZE_DIST_INFO / "RECORD").write_text("humanize/x.py,blake9=abc,1\n")

    assert broken_wheels(venv_path, [tmp_path / HUMANIZE_WHEEL]) == []


@pytest.mark.parametrize("outside_row_path", ["../../../../outside.txt", "{tmp_path}/outside.txt"])
def test_a_row_naming_a_file_outside_the_venv_is_never_read(
    tmp_path: Path, outside_row_path: str,
) -> None:
    """pip writes a wheel's RECORD rows as the wheel gives them, so a row can name any file."""
    venv_path = healthy_venv(tmp_path)
    (tmp_path / "venv-plugins/outside.txt").write_text("not what the row says")
    (tmp_path / "outside.txt").write_text("not what the row says")
    record = venv_path / SITE_PACKAGES / HUMANIZE_DIST_INFO / "RECORD"
    row_path = outside_row_path.format(tmp_path=tmp_path)
    record.write_text(record.read_text() + f"{row_path},sha256={recorded_digest(b'x')},1\n")

    assert broken_wheels(venv_path, _wheels(tmp_path)) == []


def test_a_file_two_distributions_record_marks_neither(tmp_path: Path) -> None:
    venv_path = tmp_path / "venv"
    install_distribution(venv_path, HUMANIZE_DIST_INFO, {"shared/data.py": b"humanize's bytes"})
    install_distribution(venv_path, "PyYAML-6.0.1.dist-info", {"shared/data.py": b"PyYAML's"})

    assert broken_wheels(venv_path, _wheels(tmp_path)) == []


def test_a_torn_file_two_distributions_record_marks_both(tmp_path: Path) -> None:
    venv_path = tmp_path / "venv"
    install_distribution(venv_path, HUMANIZE_DIST_INFO, {"shared/data.py": b"humanize's bytes"})
    install_distribution(venv_path, "PyYAML-6.0.1.dist-info", {"shared/data.py": b"PyYAML's"})
    (venv_path / SITE_PACKAGES / "shared/data.py").write_bytes(b"torn")

    assert broken_wheels(venv_path, _wheels(tmp_path)) == _wheels(tmp_path)


def test_a_version_the_wheel_spells_differently_still_matches(tmp_path: Path) -> None:
    """pip compares versions by value, and the dist-info takes its spelling from inside the
    wheel."""
    venv_path = tmp_path / "venv"
    install_distribution(venv_path, "notifier_lib-1.0.0rc1.dist-info", {"notifier_lib.py": b"x"})

    wheel = tmp_path / "notifier_lib-1.0.0.RC1-py3-none-any.whl"
    assert broken_wheels(venv_path, [wheel]) == []


def test_two_intact_dist_infos_of_one_distribution_leave_its_wheel_alone(tmp_path: Path) -> None:
    """A force-reinstall replaces only the one pip takes, so the other would repair forever."""
    venv_path = healthy_venv(tmp_path)
    install_distribution(venv_path, "humanize-4.14.0.dist-info", {"humanize/old.py": b"4.14.0"})

    assert broken_wheels(venv_path, _wheels(tmp_path)) == []


def test_a_torn_file_a_second_dist_info_records_marks_its_wheel(tmp_path: Path) -> None:
    venv_path = healthy_venv(tmp_path)
    site = install_distribution(
        venv_path, "humanize-4.14.0.dist-info", {"humanize/old.py": b"4.14.0"},
    )
    (site / "humanize/old.py").write_bytes(b"torn")

    assert broken_wheels(venv_path, _wheels(tmp_path)) == [tmp_path / "wheels" / HUMANIZE_WHEEL]


def test_a_file_named_like_a_dist_info_is_no_distribution(tmp_path: Path) -> None:
    venv_path = healthy_venv(tmp_path)
    (venv_path / SITE_PACKAGES / "humanize-4.14.0.dist-info").write_text("not a dir")

    assert broken_wheels(venv_path, _wheels(tmp_path)) == []


def test_a_fifo_where_a_recorded_file_was_marks_its_wheel_without_reading_it(
    tmp_path: Path,
) -> None:
    venv_path = healthy_venv(tmp_path)
    recorded_module = venv_path / SITE_PACKAGES / "humanize/__init__.py"
    recorded_module.unlink()
    os.mkfifo(recorded_module)

    assert broken_wheels(venv_path, _wheels(tmp_path)) == [tmp_path / "wheels" / HUMANIZE_WHEEL]
