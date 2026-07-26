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

## Set up your environment

Clone with the submodule. `lib_bespok3d` carries the shared gate helpers and the workspace
detectors, and nothing in this repo checks out green without it:

```sh
git clone --recurse-submodules git@github.com:Bespok3d/daemon.git
cd daemon
```

Already cloned, or seeing `lib_bespok3d/tooling/gate-lib.sh: No such file or directory`? Run this
once from the repo root:

```sh
git submodule sync --recursive && git submodule update --init --recursive
```

The `sync` half matters on an existing clone: it repoints the submodule at the relative URL, so the
submodule is fetched over whatever protocol you cloned this repo with. Without it, a clone made over
SSH still tries to fetch the submodule over HTTPS and stops at a `Username for 'https://github.com':`
prompt.

You also need these on your machine:

| Tool | Why | Install on macOS |
| --- | --- | --- |
| Python 3.11 | the printer's runtime; the gate refuses to lint or test on any other version | `brew install python@3.11`, or `brew install uv` and the gate provisions one for you |
| Node 20 or newer | runs the shared detectors (em-dash guard, workflow pinning) | `brew install node` |

The gate builds its own Python tool venv under `lib_bespok3d/tooling/` the first time you run it.
Nothing is installed into your system Python.

## Develop

```sh
bash scripts/check.sh          # the gate: em-dash guard, ruff, strict mypy, pytest on Python 3.11
sh scripts/stage-package.sh    # lay the deployable subset out as the plugin source dir CI packs
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
