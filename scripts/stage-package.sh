#!/bin/sh
# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
# Lay the daemon out as a plugin source dir so b3-builder can pack, stamp and SIGN it exactly like
# every other plugin ("b3 zero", ADR-0030). The daemon keeps its natural Python layout at the repo
# root (version.py, daemon.py, api/, core/, protocol/, the autostart scripts), which is not the shape
# a packer reads, so this stages the DEPLOYABLE subset into the shape every plugin repo already
# stores on disk: dist/package/bespok3d-daemon/{manifest.json, files/, doc/}.
#
# The only thing that stays different from a normal plugin is WHO installs it: the adapter puts this
# package on the printer at enrollment, the daemon never installs itself.
#
# Mirror the staged file list in the adapter deploy walk and package.json extraResources. EXCLUDES
# tests/, scripts/, .github/, the contributor docs, pyproject.toml, requirements-dev.txt, and every
# cache. requirements.txt ships inside files/ (the venv provisioning reads it from the installed
# tree); it deliberately does NOT sit at the staged package root, where it would arm b3-builder's
# ADR-0036 wheel bake over deps this repo already vendors under wheels/.
#
# Requires: jq.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
MANIFEST="$REPO_DIR/manifest.json"

command -v jq >/dev/null 2>&1 || { echo "ERROR: 'jq' is required." >&2; exit 1; }

name=$(jq -r '.name' "$MANIFEST")
stage_dir="$REPO_DIR/dist/package/$name"
files_root="$stage_dir/files"

rm -rf "$stage_dir"
mkdir -p "$files_root" "$stage_dir/doc"
cp -p "$MANIFEST" "$stage_dir/manifest.json"

for top_file in version.py daemon.py S99bespok3d s10bespok3d-daemon requirements.txt; do
  cp -p "$REPO_DIR/$top_file" "$files_root/$top_file"
done

# The jinni runtime is a SEPARATE app (klipper-jinni); the daemon ships only its own halves plus the
# shared `protocol` package the jinni imports. The adapter deploys the jinni runtime alongside.
for tree in api core protocol; do
  ( cd "$REPO_DIR" && find "$tree" -type f -name '*.py' ! -path '*/__pycache__/*' ) \
    | while read -r rel; do
        mkdir -p "$files_root/$(dirname "$rel")"
        cp -p "$REPO_DIR/$rel" "$files_root/$rel"
      done
done

mkdir -p "$files_root/wheels"
cp -p "$REPO_DIR"/wheels/*.whl "$files_root/wheels/"

# Ship only the user-facing docs to the printer; the contributor docs (architecture, engineering-rules)
# stay in doc/ and are not staged.
for shipped_doc in README.md CHANGELOG.md; do
  cp -p "$REPO_DIR/doc/$shipped_doc" "$stage_dir/doc/$shipped_doc"
done

echo "Staged: $stage_dir"
