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

## Quick start: from clone to pull request

Six steps. A change is ready for review when all six are done and the gate is green.

### 1. Install the tools

| Tool | Why | macOS | Linux |
| --- | --- | --- | --- |
| git 2.23 or newer | `git switch` and cloning submodules in one pass | preinstalled, or `brew install git` | `sudo apt install git` |
| Python 3.11 | the printer's runtime; the gate pins it and refuses to run on another version | `brew install python@3.11`, or `brew install uv` | install `uv` (`curl -LsSf https://astral.sh/uv/install.sh \| sh`) and the gate provisions 3.11 itself |
| Node 20 or newer | runs the shared detectors (the em-dash guard, workflow pinning) | `brew install node` | `nvm install 20`; distro packages are usually older than 20 |
| GitHub CLI (optional) | opens the pull request from the terminal | `brew install gh` | see [cli.github.com](https://cli.github.com) |

You also need an SSH key on your GitHub account (`ssh -T git@github.com` should greet you by name) and
access to the Bespok3d org: these repos are private during the beta, so ask the maintainer to add you
before you clone.

The gate builds its own Python tool venv under `lib_bespok3d/tooling/` the first time you run it.
Nothing is installed into your system Python.

### 2. Clone with the submodule

`lib_bespok3d` carries the shared gate helpers and the workspace detectors, and nothing in this repo
checks out green without it. Changes are made on `dev`, so clone that branch:

```sh
git clone --recurse-submodules --branch dev git@github.com:Bespok3d/daemon.git
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

### 3. Branch off `dev`

```sh
git switch dev && git pull
git switch -c <short-name-for-your-change>
```

### 4. Make the change

Only what your user story needs. Bump `version.py` and `manifest.json` together when the daemon's
behavior changes, update `tests/api/test_api.py`, and ship the regression test at the layer that would
catch the bug. The rules the reviewer applies are in [doc/engineering-rules.md](doc/engineering-rules.md)
and [CLAUDE.md](CLAUDE.md), and RULE ZERO (no em-dash, no en-dash) covers your commit message too.

### 5. Run the gate until it is green

```sh
bash scripts/check.sh          # em-dash guard, workflow pinning, ruff, strict mypy, pytest on Python 3.11
sh scripts/stage-package.sh    # lay the deployable subset out as the plugin source dir CI packs
```

The gate pins Python 3.11 (the device runtime): it uses a real `python3.11`, else provisions a
project-local one via `uv`, else exits rather than running on a different interpreter. On a failure, fix
the cause; never mute a check to make a number go down.

### 6. Commit, push and open the pull request

```sh
git commit -am "<what changed and why>"
git push -u origin <your-branch>
gh pr create --base dev --fill      # or open the link that git push prints
```

The pull request targets `dev`. CI runs this same `scripts/check.sh` on it, so a red gate is not
reviewable and blocks the release.

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
