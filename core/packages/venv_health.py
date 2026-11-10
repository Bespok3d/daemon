# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Find the baked wheels a plugin venv no longer holds intact, by checking each installed file
against the RECORD pip wrote for it. The record format and name matching are pure, in
`core/wheel_record.py`; this module is the reading of the venv.
"""
import csv
import hashlib
import os
from itertools import chain, groupby
from operator import attrgetter
from pathlib import Path
from typing import NamedTuple

from ..wheel_record import (
    RecordRow,
    checkable_rows,
    dist_info_distribution_name,
    encoded_digest,
    wheel_distribution_name,
)
from .members import lands_inside

# shake digests need a length pip never records, so a row naming one cannot be checked here.
_CHECKABLE_ALGORITHMS = frozenset(
    name for name in hashlib.algorithms_guaranteed if not name.startswith("shake_")
)


class InstalledDistribution(NamedTuple):
    """A dist-info dir, the normalized name of its distribution, and the checkable rows of its
    RECORD, None when that RECORD is gone, cut short or cannot be read."""

    name: str
    dist_info: Path
    rows: list[RecordRow] | None


class _FileClaim(NamedTuple):
    """What one RECORD row says an installed file holds."""

    path: Path
    algorithm: str
    encoded_digest: str


def broken_wheels(venv_path: Path, wheels: list[Path]) -> list[Path]:
    """The wheels whose dist-info is gone, or with a dist-info whose RECORD is cut short or cannot
    be read or whose recorded files are missing or changed. A wheel whose file name is not a
    wheel's is left out: pip refused it."""
    installed = _installed_distributions(venv_path)
    claims = _file_claims(installed)
    return [wheel for wheel in wheels if _is_broken(venv_path, wheel, installed, claims)]


def unrecorded_dist_infos(venv_path: Path, wheels: list[Path]) -> list[Path]:
    """The dist-info dirs of these wheels' distributions, at any version, whose RECORD is gone, cut
    short or cannot be read. pip uninstalls by that RECORD before it installs over a distribution,
    the same version or an upgrade alike, so that install fails until the dir itself is gone. Only
    a dir inside the venv is answered: the caller deletes as root."""
    baked_names = set(filter(None, (wheel_distribution_name(wheel.name) for wheel in wheels)))
    return [distribution.dist_info for distribution in _installed_distributions(venv_path)
            if distribution.name in baked_names and distribution.rows is None
            and lands_inside(venv_path, str(distribution.dist_info))]


def _installed_distributions(venv_path: Path) -> list[InstalledDistribution]:
    """pip passes over an entry named like a dist-info that is not a dir: it is no distribution."""
    dist_infos = sorted(path for path in venv_path.glob("lib/python*/site-packages/*.dist-info")
                        if path.is_dir())
    named = [(dist_info_distribution_name(dist_info.name), dist_info) for dist_info in dist_infos]
    return [InstalledDistribution(name, dist_info, _record_rows(dist_info))
            for name, dist_info in named if name is not None]


def _file_claims(installed: list[InstalledDistribution]) -> dict[Path, frozenset[_FileClaim]]:
    """What each RECORD listing a file says it holds. Two wheels may ship the same file and the one
    installed last wins it, so the file is intact when it holds what any of them recorded."""
    claims = sorted(chain.from_iterable(_claims_of(distribution) for distribution in installed))
    return {path: frozenset(same_file) for path, same_file in groupby(claims, attrgetter("path"))}


def _claims_of(distribution: InstalledDistribution) -> list[_FileClaim]:
    return [_FileClaim(_recorded_file(distribution.dist_info, row), row.algorithm,
                       row.encoded_digest) for row in distribution.rows or []]


def _recorded_file(dist_info: Path, row: RecordRow) -> Path:
    return Path(os.path.normpath(dist_info.parent / row.path))


def _is_broken(
    venv_path: Path, wheel: Path, installed: list[InstalledDistribution],
    claims: dict[Path, frozenset[_FileClaim]],
) -> bool:
    """A distribution may hold a dist-info in each lib/python* dir. Having two is not broken by
    itself: a force-reinstall replaces only the one pip takes, so it could never settle that."""
    name = wheel_distribution_name(wheel.name)
    if name is None:
        return False
    distributions = [distribution for distribution in installed if distribution.name == name]
    if not distributions:
        return True
    return any(_is_torn(venv_path, distribution, claims) for distribution in distributions)


def _is_torn(
    venv_path: Path, distribution: InstalledDistribution,
    claims: dict[Path, frozenset[_FileClaim]],
) -> bool:
    if distribution.rows is None:
        return True
    recorded_files = {_recorded_file(distribution.dist_info, row) for row in distribution.rows}
    return not all(_still_matches(venv_path, path, claims[path]) for path in recorded_files)


def _record_rows(dist_info: Path) -> list[RecordRow] | None:
    """A wheel's RECORD always hashes the METADATA it installed, so one without a single hashed row
    was cut short and vouches for nothing."""
    try:
        rows = checkable_rows((dist_info / "RECORD").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, csv.Error):
        return None
    return rows or None


def _still_matches(
    venv_path: Path, recorded_file: Path, file_claims: frozenset[_FileClaim],
) -> bool:
    """pip writes a wheel's RECORD rows as the wheel gives them, so a row may name any file on the
    printer: one outside the venv is not this venv's to vouch for, and is never opened."""
    if not lands_inside(venv_path, str(recorded_file)):
        return True
    if any(claim.algorithm not in _CHECKABLE_ALGORITHMS for claim in file_claims):
        return True
    return any(_file_digest(recorded_file, claim.algorithm) == claim.encoded_digest
               for claim in file_claims)


def _file_digest(installed_file: Path, algorithm: str) -> str | None:
    """A FIFO put where a file was would block the read forever, so only a regular file is read."""
    if not installed_file.is_file():
        return None
    try:
        with installed_file.open("rb") as installed_bytes:
            return encoded_digest(hashlib.file_digest(installed_bytes, algorithm).digest())
    except OSError:
        return None
