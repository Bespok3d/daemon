# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reading pip's RECORD and matching a baked wheel to the dist-info pip installed it as."""
import base64
import hashlib

import pytest

from core.wheel_record import (
    RecordRow,
    checkable_rows,
    dist_info_distribution_name,
    encoded_digest,
    wheel_distribution_name,
)


@pytest.mark.parametrize(
    ("wheel_filename", "dist_info_dirname"),
    [
        ("humanize-4.15.0-py3-none-any.whl", "humanize-4.15.0.dist-info"),
        ("PyYAML-6.0.1-cp311-cp311-linux_aarch64.whl", "pyyaml-6.0.1.dist-info"),
        ("zope.interface-6.1-cp311-cp311-linux_aarch64.whl", "zope_interface-6.1.dist-info"),
        ("typing_extensions-4.9.0-py3-none-any.whl", "typing-extensions-4.9.0.dist-info"),
        ("pkg-1.0-1build-py3-none-any.whl", "pkg-1.0.dist-info"),
        ("notifier_lib-1.0.0.RC1-py3-none-any.whl", "notifier_lib-1.0.0rc1.dist-info"),
    ],
)
def test_a_wheel_matches_the_dist_info_pip_installs_it_as(
    wheel_filename: str, dist_info_dirname: str,
) -> None:
    assert wheel_distribution_name(wheel_filename) == dist_info_distribution_name(dist_info_dirname)


def test_the_version_is_not_part_of_the_match() -> None:
    installed = dist_info_distribution_name("humanize-4.14.0.dist-info")

    assert wheel_distribution_name("humanize-4.15.0-py3-none-any.whl") == installed


@pytest.mark.parametrize("not_a_wheel", ["humanize-4.15.0.tar.gz", "humanize-4.15.0.whl"])
def test_a_file_name_that_is_not_a_wheels_has_no_distribution(not_a_wheel: str) -> None:
    assert wheel_distribution_name(not_a_wheel) is None


@pytest.mark.parametrize("not_a_dist_info", ["humanize", "humanize.dist-info", "x.egg-info"])
def test_a_dir_name_that_is_not_a_dist_infos_has_no_distribution(not_a_dist_info: str) -> None:
    assert dist_info_distribution_name(not_a_dist_info) is None


def test_the_distribution_name_is_normalized() -> None:
    assert dist_info_distribution_name("Zope.Interface-6.1.dist-info") == "zope_interface"


def test_only_the_rows_with_a_digest_are_checkable() -> None:
    record_text = (
        "humanize/__init__.py,sha256=abc,120\n"
        "../../../bin/humanize,sha256=def,250\n"
        '"humanize/a, comma.py",sha256=ghi,3\n'
        "humanize/__pycache__/__init__.cpython-311.pyc,,\n"
        "humanize-4.15.0.dist-info/RECORD,,\n"
        "\n"
    )

    assert checkable_rows(record_text) == [
        RecordRow("humanize/__init__.py", "sha256", "abc"),
        RecordRow("../../../bin/humanize", "sha256", "def"),
        RecordRow("humanize/a, comma.py", "sha256", "ghi"),
    ]


def test_a_row_whose_path_holds_a_line_break_character_stays_one_row() -> None:
    """Python splits text lines on more characters than the newline pip ends each row with."""
    record_text = "humanize/form\x0cfeed.py,sha256=abc,3\n"

    assert checkable_rows(record_text) == [RecordRow("humanize/form\x0cfeed.py", "sha256", "abc")]


def test_the_digest_is_encoded_the_way_pip_records_it() -> None:
    digest = hashlib.sha256(b"port = 7912\n").digest()

    assert encoded_digest(digest) == base64.urlsafe_b64encode(digest).decode().rstrip("=")
    assert "=" not in encoded_digest(digest)
