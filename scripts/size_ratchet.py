# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Size ratchet: a god file is a failing, visible check, so a concern-mixing file cannot re-form
unnoticed (the ADR-0037 cleanup must not regress). Reads size-baseline.json and enforces:

  1. No file over the .py ceiling unless it is an allowlisted, reviewed exception.
  2. Equal-or-tighten on each allowlisted file: growth FAILs; a shrink FAILs asking you to lower the
     baseline (the ratchet click, so an improvement is banked as a reviewed edit).

It governs production source and test INFRASTRUCTURE (conftest, fakes); the test SUITES (test_*.py,
append-only case collections) are out of scope. The ceiling is a SIGNAL, not the law: when it fires,
split the file by concern, never allowlist your own bloat. Exit 0 only when clean.
"""
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_BASELINE = json.loads((_ROOT / "size-baseline.json").read_text())
_CEILING: int = _BASELINE["pyCeiling"]
_ALLOWLIST: dict[str, int] = _BASELINE["allowlist"]
_SOURCE_DIRS = ("core", "api", "protocol", "tests")
_EXCLUDED_DIRS = {"__pycache__", ".venv", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def _is_governed(path: Path) -> bool:
    """A .py file the ratchet measures: production source or test infra. A test SUITE (test_*.py)
    is an append-only case collection, out of scope; its infra (conftest, fakes) is governed."""
    if any(part in _EXCLUDED_DIRS for part in path.parts):
        return False
    return not path.name.startswith("test_")


def _line_count(path: Path) -> int:
    text = path.read_text()
    return len(text.rstrip("\n").split("\n")) if text.strip() else 0


def _observed() -> dict[str, int]:
    counts: dict[str, int] = {}
    for source_dir in _SOURCE_DIRS:
        for path in sorted((_ROOT / source_dir).rglob("*.py")):
            if _is_governed(path):
                counts[str(path.relative_to(_ROOT))] = _line_count(path)
    return counts


def _over_ceiling(counts: dict[str, int]) -> list[str]:
    return [f"NEW over-ceiling: {rel} ({lines} > {_CEILING}); split it by concern, never allowlist bloat"  # noqa: E501
            for rel, lines in counts.items() if lines > _CEILING and rel not in _ALLOWLIST]


def main() -> int:
    counts = _observed()
    failures = _over_ceiling(counts)
    tighten: list[str] = []
    for rel, base in _ALLOWLIST.items():
        current = counts.get(rel)
        if current is None:
            failures.append(f"allowlisted file missing or out of scope: {rel} (update size-baseline.json)")  # noqa: E501
        elif current > base:
            failures.append(f"GROWTH {rel}: {current} > baseline {base}; split it, do not grow it")
        elif current < base:
            tighten.append(f"{rel}: lower baseline {base} -> {current}")
    if not failures and not tighten:
        print(f"ratchet ok - {len(counts)} files, {len(_ALLOWLIST)} allowlisted")
        return 0
    for message in tighten:
        print(f"  tighten (bank it): {message}", file=sys.stderr)
    for message in failures:
        print(f"  FAIL: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
