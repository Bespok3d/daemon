# bespok3d-daemon

The on-printer daemon for the Bespok3d plugin manager. See [doc/README.md](doc/README.md) for what it
does and how it is deployed, and [doc/CHANGELOG.md](doc/CHANGELOG.md) for the version history.

## Layout

The daemon keeps a natural Python layout at the repo root (the packer maps the deployable subset into
a `.b3`'s internal `files/`):

```
version.py            DAEMON_VERSION, the single source of truth for the version
daemon.py             entrypoint
api/                  FastAPI app, routes, middleware
core/                 install / uninstall / recovery / safety / intent / auth ...
jinni/                generic base jinni + loader (device-specific jinnis live in adapters/)
S99bespok3d           boot hook
s10bespok3d-daemon    autostart script
wheels/               prebuilt offline runtime deps (pgpy)
requirements.txt      runtime deps
tests/                test suite (not packed)
scripts/              check.sh / pack.sh / generate-atom.mjs (not packed)
manifest.json         b3-zero manifest (version mirrors version.py)
doc/                  README + CHANGELOG (shipped in the .b3)
```

## Develop

```sh
# Run the full gate (ruff + mypy + pytest). Requires python3.11 or uv, plus zip/jq for packing.
bash scripts/check.sh

# Build the publishable package -> dist/bespok3d-daemon-<version>.b3
sh scripts/pack.sh

# Inspect the index atom that CI publishes (dry run, local download_url)
node scripts/generate-atom.mjs
```

`scripts/check.sh` pins Python 3.11 (the device runtime): it prefers a real `python3.11`, else
provisions a project-local one via `uv`, else exits rather than running on a different interpreter.

## Versioning

Bump `version.py` (`DAEMON_VERSION`) and `manifest.json` (`version`) together; `pack.sh` refuses to
build if they disagree. Keep the app-side mirror (`EXPECTED_DAEMON_VERSION` in the Bespok3d app) and
`tests/test_api.py` in sync when bumping.

## Releasing

A push to `main` touching the daemon source, manifest, version, or scripts triggers
`.github/workflows/release.yml`: it runs the gate, packs the `.b3`, and publishes a GitHub release with
the `.b3` and its index atom attached.
