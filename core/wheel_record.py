# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The pure side of checking an installed wheel against the RECORD pip wrote for it.

pip skips a wheel whose name and version are already installed, so a venv file a power cut or a
full disk left torn stays torn on every later install. Each installed distribution keeps a
`<name>-<version>.dist-info/RECORD` listing every file it installed as `path,<algorithm>=<urlsafe
base64 digest, no padding>,size`; a file that no longer matches its row is what marks the wheel
for a reinstall. The IO that reads the venv lives in `core/packages/venv_health.py`.

A wheel is matched to its dist-info by name only. pip compares versions by value, while the
dist-info takes its spelling from inside the wheel, so `1.0.0.RC1` in a wheel file name lands as
`1.0.0rc1`; and once the offline install went through, each baked name holds the baked version.
"""
import base64
import csv
import io
import re
from typing import NamedTuple

_DIST_INFO_SUFFIX = ".dist-info"
_WHEEL_SUFFIX = ".whl"
_NAME_SEPARATORS = re.compile(r"[-_.]+")
_WHEEL_NAME_FIELDS = 5
_RECORD_PATH_AND_HASH = 2


class RecordRow(NamedTuple):
    """One installed file: its path from the site-packages dir, and the digest pip recorded."""

    path: str
    algorithm: str
    encoded_digest: str


def normalized_name(distribution_name: str) -> str:
    """PEP 503 normalization, with the `_` PEP 427 puts in wheel and dist-info names."""
    return _NAME_SEPARATORS.sub("_", distribution_name).lower()


def wheel_distribution_name(wheel_filename: str) -> str | None:
    """`<name>-<version>[-<build>]-<python>-<abi>-<platform>.whl`; None for any other file name."""
    if not wheel_filename.endswith(_WHEEL_SUFFIX):
        return None
    name_parts = wheel_filename.removesuffix(_WHEEL_SUFFIX).split("-")
    if len(name_parts) < _WHEEL_NAME_FIELDS:
        return None
    return normalized_name(name_parts[0])


def dist_info_distribution_name(dist_info_dirname: str) -> str | None:
    """`<name>-<version>.dist-info`; None for any other dir name."""
    if not dist_info_dirname.endswith(_DIST_INFO_SUFFIX):
        return None
    name, separator, version = dist_info_dirname.removesuffix(_DIST_INFO_SUFFIX).rpartition("-")
    if not (separator and name and version):
        return None
    return normalized_name(name)


def checkable_rows(record_text: str) -> list[RecordRow]:
    """The rows that carry a digest. pip leaves the digest empty for RECORD itself and for the
    bytecode it compiles after install, and those cannot be checked."""
    rows = [_record_row(columns) for columns in csv.reader(io.StringIO(record_text, newline=""))]
    return [row for row in rows if row is not None]


def _record_row(columns: list[str]) -> RecordRow | None:
    if len(columns) < _RECORD_PATH_AND_HASH:
        return None
    algorithm, _separator, digest = columns[1].partition("=")
    if not (columns[0] and algorithm and digest):
        return None
    return RecordRow(columns[0], algorithm, digest)


def encoded_digest(digest: bytes) -> str:
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
