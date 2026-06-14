#!/bin/sh
# Pack the daemon into a publishable .b3 ("b3 zero", ADR-0030). The daemon keeps its natural Python
# layout at the repo root (version.py, daemon.py, api/, core/, jinni/, the autostart scripts), so this
# stages the DEPLOYABLE subset into a temp files/ tree, records each file's sha256 + mode into
# manifest.files[], then zips files/ + doc/ + manifest.json into dist/bespok3d-daemon-<version>.b3 (the
# same shape a solo-plugin .b3 has). Always repacks; bump version.py + manifest.json to cut a version.
#
# Requires: zip, jq, and shasum (macOS) or sha256sum (Linux).
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
DIST_DIR="$REPO_DIR/dist"
MANIFEST="$REPO_DIR/manifest.json"

for cmd in zip jq; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "ERROR: '$cmd' is required." >&2; exit 1; }
done
command -v shasum >/dev/null 2>&1 || command -v sha256sum >/dev/null 2>&1 \
  || { echo "ERROR: shasum or sha256sum is required." >&2; exit 1; }

file_sha256() {
  if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
  else sha256sum "$1" | awk '{print $1}'; fi
}

file_mode() { stat -f "%OLp" "$1" 2>/dev/null || stat -c "%a" "$1" 2>/dev/null; }

name=$(jq -r '.name' "$MANIFEST")
version=$(jq -r '.version' "$MANIFEST")

# Single source of truth: the manifest version must match version.py (the daemon's runtime version),
# so a release can never ship a .b3 whose advertised version differs from what the daemon reports.
code_version=$(sed -n 's/^DAEMON_VERSION *= *"\(.*\)"/\1/p' "$REPO_DIR/version.py")
if [ "$version" != "$code_version" ]; then
  echo "ERROR: manifest version ($version) != version.py DAEMON_VERSION ($code_version). Bump both." >&2
  exit 1
fi

# Stage the deployable subset (what the adapter puts on the printer) into a temp files/ tree. Mirror
# this list in the adapter deploy walk and package.json extraResources. EXCLUDES tests/, scripts/,
# .github/, doc/, pyproject.toml, requirements-dev.txt, and every cache.
stage_dir=$(mktemp -d)
files_root="$stage_dir/files"
mkdir -p "$files_root"

for top_file in version.py daemon.py S99bespok3d s10bespok3d-daemon requirements.txt; do
  cp -p "$REPO_DIR/$top_file" "$files_root/$top_file"
done

for tree in api core jinni; do
  ( cd "$REPO_DIR" && find "$tree" -type f -name '*.py' ! -path '*/__pycache__/*' ) \
    | while read -r rel; do
        mkdir -p "$files_root/$(dirname "$rel")"
        cp -p "$REPO_DIR/$rel" "$files_root/$rel"
      done
done

mkdir -p "$files_root/wheels"
cp -p "$REPO_DIR"/wheels/*.whl "$files_root/wheels/"

# files[] array: every staged file -> {path, sha256, mode}. LC_ALL=C forces a locale-stable byte sort
# so the file list (and any hash over it) is identical on every machine.
build_files_array() {
  ( cd "$stage_dir" && find files -type f ! -name '.DS_Store' ) | LC_ALL=C sort | while read -r rel; do
    sha=$(file_sha256 "$stage_dir/$rel")
    mode=$(file_mode "$stage_dir/$rel")
    case "$mode" in *7*) mode="755" ;; *) mode="644" ;; esac
    printf '{"path":"%s","sha256":"%s","mode":"%s"}\n' "$rel" "$sha" "$mode"
  done
}

files_json=$(build_files_array | jq -s '.')
jq --argjson files "$files_json" '.files = $files' "$MANIFEST" > "$stage_dir/manifest.json"

mkdir -p "$DIST_DIR"
output="$DIST_DIR/$name-$version.b3"
rm -f "$output"
(
  cd "$stage_dir"
  zip -qr "$output" files/
  zip -q "$output" manifest.json
)
if [ -d "$REPO_DIR/doc" ]; then ( cd "$REPO_DIR" && zip -qr "$output" doc/ ); fi
rm -rf "$stage_dir"

echo "Packed: $output"
echo "  sha256: $(file_sha256 "$output")"
