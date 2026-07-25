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
protocol/             the contract the daemon and the jinni both import (the jinni runtime is its own
                      app, adapters/klipper-jinni)
S99bespok3d           boot hook
s10bespok3d-daemon    autostart script
wheels/               prebuilt offline runtime deps (pgpy)
requirements.txt      runtime deps
tests/                test suite (not packed)
scripts/              check.sh / stage-package.sh (not packed)
manifest.json         b3-zero manifest (version mirrors version.py)
doc/                  README + CHANGELOG (shipped in the .b3); architecture + engineering-rules (not shipped)
```

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) first. The rules every change follows are in
[doc/engineering-rules.md](doc/engineering-rules.md) (software-engineering rules, enforced in the gate),
and the design intent and concern map are in [doc/architecture.md](doc/architecture.md). If you use an AI
assistant, point it at [CLAUDE.md](CLAUDE.md), which encodes the same rules and the working procedure.

## Develop

```sh
# Run the full gate (ruff + mypy + pytest). Requires python3.11 or uv, plus jq for staging.
bash scripts/check.sh

# Lay the deployable subset out as a plugin source dir -> dist/package/bespok3d-daemon/
sh scripts/stage-package.sh

# Browse the HTTP API locally: serves on http://localhost:4269/docs (dev mode, no auth, fake jinni)
bash scripts/serve-local.sh
```

`scripts/check.sh` pins Python 3.11 (the device runtime): it prefers a real `python3.11`, else
provisions a project-local one via `uv`, else exits rather than running on a different interpreter.

## Versioning

Bump `version.py` (`DAEMON_VERSION`) and `manifest.json` (`version`) together; the gate fails if they
disagree (`tests/test_manifest_version.py`), and update `tests/api/test_api.py` when bumping. The
Bespok3d app derives its expected version from `version.py` at build time, so there is no
`EXPECTED_DAEMON_VERSION` mirror to keep in sync.

## Releasing

A push to `main` touching the daemon source, manifest, version, or scripts triggers
`.github/workflows/release.yml`: it runs the gate, stages the daemon as a plugin source dir, and hands
it to the org-wide `b3-builder` Action, which packs the `.b3`, stamps the publisher, signs the manifest
and publishes a GitHub release with the `.b3` and its index atom attached.

The daemon is plugin zero: same package shape, same signature, same release layout as any
plugin. The single difference is that the adapter puts it on the printer at enrollment, so it is never
installed through the plugin pipeline and is not registered in the catalog.
