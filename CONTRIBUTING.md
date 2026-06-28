# Contributing

Thanks for working on the Bespok3d daemon. This repo holds the on-printer service; see
[README.md](README.md) for what it is and how it is deployed.

## Before you write code

Read [doc/engineering-rules.md](doc/engineering-rules.md) and [doc/architecture.md](doc/architecture.md).
The rules are software-engineering rules (naming, nesting, separation of concerns, the generic-versus-
device boundary, rule of three, resilience), not Python style preferences, and they are enforced. The
architecture doc tells you where a new concern belongs so you grow the right file instead of a god file.

If you use an AI assistant for your change (many contributors do), point it at [CLAUDE.md](CLAUDE.md): it
encodes the same rules and the working procedure so the assistant produces a change the review will
accept.

## Develop

```sh
bash scripts/check.sh          # the gate: em-dash guard, ruff, strict mypy, pytest on Python 3.11
sh scripts/pack.sh             # build the publishable .b3 into dist/
node scripts/generate-atom.mjs # inspect the index atom CI publishes (dry run)
```

The gate pins Python 3.11 (the device runtime): it uses a real `python3.11`, else provisions a
project-local one via `uv`, else exits rather than running on a different interpreter. Run it before every
push; CI runs the same gate and blocks a release on failure.

## What a good change looks like

- Scoped to a clear user story; only what the story needs.
- Follows the rules above; passes the gate green.
- Ships a regression test at the layer that would catch the bug, in the same change.
- Keeps the docs current when it changes a boundary, an invariant, or where a concern lives.
- Bumps `version.py` and `manifest.json` together when it changes the daemon's behavior, and updates
  `tests/api/test_api.py`. The app-side expected version is generated from `version.py` at build time, so
  there is no `EXPECTED_DAEMON_VERSION` mirror to keep in sync.

## Constraints

- The maintainer owns git history and releases; submit changes as a PR.
- Do not weaken the invariants in architecture.md (printer-never-broken, venv isolation, auth on every
  route, version single-source).
