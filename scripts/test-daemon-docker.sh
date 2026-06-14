#!/usr/bin/env bash
# Run the daemon tests + mutation on the TARGET Python (3.11) inside Docker. Nothing is installed on the
# dev machine: the source is copied into the image and run there. Use this for on-target verification and
# to generate the Python mutation baseline (mutmut does not run on a newer dev-machine python like 3.14).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PURE_CORES="core/intent.py,core/print_events.py,core/auth.py"
PROP_TESTS="tests/core/test_intent_props.py tests/core/test_print_events_props.py tests/core/test_auth_props.py"

if ! docker info > /dev/null 2>&1; then
    echo "Docker is not running. Start Docker and retry." >&2
    exit 1
fi

echo "Building the daemon-test image (Python 3.11, source copied in)..."
docker build -t bespok3d/daemon-test:latest -f "$REPO_ROOT/daemon-test.Dockerfile" "$REPO_ROOT"

echo ""
echo "=== Daemon tests on Python 3.11 ==="
docker run --rm bespok3d/daemon-test:latest pytest -q tests

echo ""
echo "=== Mutation (mutmut) on the pure cores ==="
docker run --rm bespok3d/daemon-test:latest sh -c \
    "mutmut run --paths-to-mutate '$PURE_CORES' --tests-dir tests/ --runner 'pytest -x -q $PROP_TESTS' > /dev/null 2>&1 || true; mutmut results"
