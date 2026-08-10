# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The one dotted-numeric version comparison in the daemon.

Every version question the daemon asks is the same question (does this firmware reach a manifest's
`fw_min`, is the jinni on this printer new enough for this daemon), so it is answered in one place.
The app asks it in TypeScript, in `@bespok3d/contract`; those two are the only comparators in the
system and they answer by the same rule.

The rule: dotted numeric, the shorter side zero-padded so `1.4` and `1.4.0` are equal, and a version
that is not purely numeric compares to nothing at all. Answering None rather than False keeps "older
than the floor" apart from "no readable version", which is the difference between a pair that is
proven bad and a question that could not be asked.
"""


def compare_versions(version: str, bound: str) -> int | None:
    """`version` against `bound` as -1 / 0 / 1 by dotted-numeric order, or None when either side is
    not purely numeric (an 'unknown' or malformed version compares to nothing)."""
    version_key, bound_key = _numeric_key(version), _numeric_key(bound)
    if version_key is None or bound_key is None:
        return None
    left, right = _zero_padded(version_key, bound_key)
    return (left > right) - (left < right)


def version_at_least(version: str, floor: str) -> bool:
    """True when `version` reads as a number and reaches `floor`. An unreadable version reaches no
    floor."""
    order = compare_versions(version, floor)
    return order is not None and order >= 0


def version_at_most(version: str, ceiling: str) -> bool:
    """True when `version` reads as a number and does not exceed `ceiling`."""
    order = compare_versions(version, ceiling)
    return order is not None and order <= 0


def known_to_be_below(version: str, floor: str) -> bool:
    """True only when BOTH sides read as numbers AND `version` is older than `floor`: a pair the
    daemon can prove is bad. An unreadable version answers False here and False from
    `version_at_least` too, because it is neither proven good nor proven bad, and refusing on it
    would turn a question the daemon could not ask into a printer it will not serve."""
    order = compare_versions(version, floor)
    return order is not None and order < 0


def _numeric_key(version: str) -> tuple[int, ...] | None:
    # str(): a bound written unquoted (`"fw_min": 1.5`) reaches here as a JSON number; coerce so the
    # version the author meant compares, rather than crashing on `.split` of a float.
    parts = str(version).split(".")
    if not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def _zero_padded(
    left: tuple[int, ...], right: tuple[int, ...]
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Zero-pad the shorter key so 1.4 and 1.4.0 compare equal, not 1.4 < 1.4.0."""
    width = max(len(left), len(right))
    return left + (0,) * (width - len(left)), right + (0,) * (width - len(right))
