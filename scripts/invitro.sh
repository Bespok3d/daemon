#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
# Runs the daemon's in-vitro suite against a REAL printer, over the same HTTPS wire the app uses.
# The refusal tier runs by default: it offers packages the printer must turn away, so nothing is
# installed. Set B3D_INVITRO_MUTATE=1 to also run the tests that really install a throwaway package
# and take it off again. The printer address comes from B3D_HIL_HOST.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTEST="$REPO_ROOT/.venv/bin/pytest"

if [ -z "${B3D_HIL_HOST:-}" ]; then
    echo "B3D_HIL_HOST is not set. Point it at the printer to test, for example:" >&2
    echo "  B3D_HIL_HOST=<printer-address> bash scripts/invitro.sh" >&2
    exit 1
fi

if [ ! -x "$PYTEST" ]; then
    echo "The daemon's python tools are not provisioned yet. Run this once, then retry:" >&2
    echo "  bash scripts/check.sh" >&2
    exit 1
fi

cd "$REPO_ROOT" || exit 1

if [ "${B3D_INVITRO_MUTATE:-0}" = "1" ]; then
    echo "in-vitro suite against $B3D_HIL_HOST: refusals + install tiers"
    exec "$PYTEST" --tb=short -q tests_invitro
fi

echo "in-vitro suite against $B3D_HIL_HOST: refusals tier (B3D_INVITRO_MUTATE=1 adds the install)"
exec "$PYTEST" --tb=short -q -m "not mutating" tests_invitro
