#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
set -euo pipefail

DAEMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$DAEMON_DIR/.venv"
SANDBOX="$DAEMON_DIR/.dev-sandbox"

if [ ! -d "$VENV" ]; then
    echo "venv not found; run ./scripts/check.sh first to set it up"
    exit 1
fi

mkdir -p "$SANDBOX/auth" "$SANDBOX/usr/local/plugins"

TOKEN_FILE="$SANDBOX/auth/dev-token"
if [ ! -f "$TOKEN_FILE" ]; then
    openssl rand -hex 16 > "$TOKEN_FILE"
fi
TOKEN="$(cat "$TOKEN_FILE")"

cat > "$SANDBOX/auth/acl.json" <<EOF
{
  "keys": [],
  "roles": {},
  "tokens": ["$TOKEN"]
}
EOF

echo ""
echo "Bespok3d daemon: dev mode"
echo "  Sandbox : $SANDBOX"
echo "  Token   : $TOKEN"
echo "  API     : http://localhost:4269"
echo "  Docs    : http://localhost:4269/docs"
echo ""

export BESPOK3D_DATA_ROOT="$SANDBOX"
export BESPOK3D_ADAPTER="${BESPOK3D_ADAPTER:-generic}"

exec "$VENV/bin/python3" "$DAEMON_DIR/daemon.py"
