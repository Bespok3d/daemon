#!/bin/sh
# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Fills wheels/ with the daemon's runtime packages built for the printer, so enrollment installs
# them with the package index switched off and the printer needs no internet connection.
#
# Run on a workstation with internet access whenever the runtime packages change, then commit what
# it writes.
set -eu

# The printer runs CPython 3.11 on aarch64 against glibc, so the wheels are resolved for that target
# rather than for the workstation running this script.
PYTHON_VERSION=311
PLATFORM=manylinux2014_aarch64

cd "$(dirname "$0")/.."

python3 -m pip download \
  --only-binary=:all: \
  --implementation cp \
  --python-version "$PYTHON_VERSION" \
  --abi "cp$PYTHON_VERSION" \
  --platform "$PLATFORM" \
  --dest wheels \
  fastapi 'uvicorn[standard]' python-multipart

echo
echo "wheels/ now holds:"
ls -1 wheels
