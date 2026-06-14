#!/usr/bin/env python3
"""RULE ZERO guard: fail the gate if any authored file contains an em-dash or en-dash.

The em-dash (U+2014) and en-dash (U+2013) are banned everywhere in Bespok3d. No linter enforces
this, so this guard walks the daemon repo and exits non-zero on any offender. Only authored text
formats are scanned, by suffix (plus the two extensionless init scripts); build output, the
virtualenv, caches, git internals, prebuilt wheels, and the dist/ packages are skipped. The dash
codepoints are written as escapes here so the guard never trips on itself.
"""
import sys
from pathlib import Path

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
SCANNED_SUFFIXES = (".py", ".md", ".json", ".sh", ".mjs", ".toml", ".txt")
INIT_SCRIPTS = ("S99bespok3d", "s10bespok3d-daemon")
EXCLUDED_DIRS = (
    "dist", ".venv", ".git", "__pycache__", "wheels", "node_modules",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".hypothesis",
)


def is_scanned(path: Path) -> bool:
    if not path.is_file():
        return False
    if any(part in EXCLUDED_DIRS for part in path.parts):
        return False
    return path.suffix in SCANNED_SUFFIXES or path.name in INIT_SCRIPTS


def has_banned_dash(path: Path) -> bool:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return EM_DASH in text or EN_DASH in text


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    candidates = (path for path in repo_root.rglob("*") if is_scanned(path))
    offenders = [path for path in candidates if has_banned_dash(path)]
    for path in offenders:
        print(f"RULE ZERO violation (em-dash/en-dash): {path.relative_to(repo_root)}")
    return 1 if offenders else 0


if __name__ == "__main__":
    sys.exit(main())
