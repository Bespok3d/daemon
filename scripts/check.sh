#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
set -euo pipefail

# The daemon's self-contained gate: ruff + mypy + pytest on Python 3.11 (the device runtime). It
# resolves the repo root from its own path and runs every check with cwd=repo so the daemon's
# pyproject.toml (ruff rules + strict mypy + pytest config) is discovered and applied. Running mypy
# from a directory without that config silently downgrades it to lenient defaults, which is exactly how
# 19 genuine type errors stayed hidden while the daemon lived inside the monorepo gate.
#
# Python 3.11 is REQUIRED: the printer runs it, a newer local interpreter hides target-vs-test
# mismatches, and mypy still checks 3.11 syntax. Prefer a real python3.11; else provision a
# PROJECT-LOCAL one via uv (a standalone build in uv's cache, never a system install); else exit
# loudly. Never silently fall back to another interpreter.

export PYTHONDONTWRITEBYTECODE=1

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$REPO_DIR/.venv"

# The detectors that enforce a workspace-wide rule live in one place and are invoked by every repo's
# gate. See lib_bespok3d/tooling/README.md. This is the only line that knows where they are.
B3D_TOOLING="${B3D_TOOLING:-$REPO_DIR/lib_bespok3d/tooling}"
# lib_bespok3d is a submodule. A clone made without it leaves an empty directory here, so say what
# is actually wrong instead of letting every check below fail on a missing file.
if [ ! -f "$B3D_TOOLING/em-dash-guard.mjs" ]; then
    echo "The shared gate helpers are missing: the lib_bespok3d submodule is not checked out." >&2
    echo "Run this once from the repo root, then try again:" >&2
    echo "  git submodule sync --recursive && git submodule update --init --recursive" >&2
    echo "See CONTRIBUTING.md for the full environment setup." >&2
    exit 1
fi

cd "$REPO_DIR"

PASS=0
FAIL=0
FAILURES=""

run_check() {
    local label="$1"
    shift
    printf "  %-28s" "$label"
    if "$@" > /tmp/daemon_check_out 2>&1; then
        echo "ok"
        PASS=$((PASS + 1))
    else
        echo "FAIL"
        FAIL=$((FAIL + 1))
        FAILURES="$FAILURES\n--- $label ---\n$(cat /tmp/daemon_check_out)\n"
    fi
}

PYTHON_BIN=""
if command -v python3.11 > /dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3.11)"
elif command -v uv > /dev/null 2>&1; then
    uv python install 3.11 > /dev/null 2>&1 || true
    PYTHON_BIN="$(uv python find 3.11 2> /dev/null || true)"
fi
if [ -z "$PYTHON_BIN" ] || ! "$PYTHON_BIN" --version 2>&1 | grep -q "^Python 3\.11\."; then
    echo "ERROR: Python 3.11 (the daemon's target runtime) is required but was not found and could" >&2
    echo "       not be provisioned. Install python3.11 or uv; refusing to run on another interpreter." >&2
    exit 2
fi

if [ -d "$VENV" ] && ! "$VENV/bin/python" --version 2>&1 | grep -q "^Python 3\.11\."; then
    echo "Daemon .venv is $("$VENV/bin/python" --version 2>&1), not 3.11; rebuilding..."
    rm -rf "$VENV"
fi
if [ ! -d "$VENV" ]; then
    echo "Creating .venv ($("$PYTHON_BIN" --version 2>&1))..."
    "$PYTHON_BIN" -m venv "$VENV"
    echo "Installing dependencies..."
    "$VENV/bin/pip" install --quiet -r requirements.txt -r requirements-dev.txt
fi

echo "Daemon gate (Python $("$VENV/bin/python" --version 2>&1 | awk '{print $2}'))"
run_check "em-dash / en-dash ban" node "$B3D_TOOLING/em-dash-guard.mjs" "$REPO_DIR" \
    --name S99bespok3d --name s10bespok3d-daemon
run_check "workflow pinning"      node "$B3D_TOOLING/workflow-pinning-detector.mjs" "$REPO_DIR"
run_check "cross-file private imports" "$VENV/bin/python" scripts/private_import_guard.py
run_check "generic-daemon boundary" "$VENV/bin/python" scripts/generic_daemon_guard.py
run_check "size ratchet" "$VENV/bin/python" scripts/size_ratchet.py
run_check "pytest" "$VENV/bin/pytest" --tb=short -q
run_check "ruff"   "$VENV/bin/ruff" check .
run_check "mypy"   "$VENV/bin/mypy" .

echo ""
echo "  $PASS passed, $FAIL failed"
if [ "$FAIL" -ne 0 ]; then
    printf "%b" "$FAILURES" >&2
    exit 1
fi
