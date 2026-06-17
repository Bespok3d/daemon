#!/usr/bin/env bash
set -euo pipefail

# Stand the daemon up locally (HTTP, no auth, fake jinni) to browse its Swagger/OpenAPI UI at
# http://localhost:4269/docs. DEV ONLY: never how the daemon runs on a printer. Reuses the Python
# 3.11 .venv that scripts/check.sh builds; the heavy lifting is in scripts/serve_local.py.
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$REPO_DIR/.venv"
cd "$REPO_DIR"

if [ ! -x "$VENV/bin/python" ]; then
    echo "No .venv yet. Run 'bash scripts/check.sh' once to build it, then re-run this." >&2
    exit 2
fi

# Put the repo root on the path so the launcher imports core/api/tests (it lives in scripts/, not root).
exec env PYTHONPATH="$REPO_DIR${PYTHONPATH:+:$PYTHONPATH}" "$VENV/bin/python" scripts/serve_local.py
