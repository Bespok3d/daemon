# bespok3d-daemon: instructions for AI assistants

You are working in the Bespok3d daemon, the on-printer service for a Klipper plugin manager. This file is
the contract for any LLM or agent that touches this repo. Contributors here often use AI assistance, so
these rules and the design intent are written down and enforced in the gate, not left implicit. Read them
and uphold them; the human reviewer rejects a PR that ignores them.

If you are a non-Claude tool, `AGENTS.md` points you here.

## Read these first

- [doc/engineering-rules.md](doc/engineering-rules.md): the rules every change follows. These are
  software-engineering rules, not Python rules; they apply identically across the wider Bespok3d codebase.
  Read it fully before writing code. Its opening section is the WHY: code has two bounded-context readers
  (a human and an LLM), every rule exists to lower the context needed to make a safe local change, and the
  objective is human cognitive load (a lean machine context is the correlated side effect, never the
  target). Apply the rules in that spirit, not just to the letter.
- [doc/architecture.md](doc/architecture.md): what the daemon is, the generic-versus-device boundary, the
  HTTP-versus-websocket boundary, the invariants, and where each concern lives (and is moving to).
- [README.md](README.md) for build/version/release mechanics; [CONTRIBUTING.md](CONTRIBUTING.md) for the
  contribution flow.
- [doc/internals/install-and-update.md](doc/internals/install-and-update.md): every check the printer runs before it accepts
  a package, the two version floors, and what a refusal leaves behind. An update runs the install
  checks; there is no relaxed update path.
- [doc/internals/patch-pipeline.md](doc/internals/patch-pipeline.md): how a plugin's diffs reach a file the printer owns,
  where the stock original is kept and how it is keyed, and how ownership of a patched file is handed
  over.

## The non-negotiables (the floor; full treatment in engineering-rules.md)

1. **Every identifier carries domain meaning.** A name says what the thing *is* in the domain, never its
   type, position, or a role-free abbreviation. No `a`/`b`, `tmp`, `data`, single letters.
2. **Nesting beyond one level is suspicious.** Flatten by default: guard clauses, early returns, extracted
   named functions, a named lookup instead of a nested ternary. When you must nest, comment why.
3. **Separation of concerns.** One responsibility per file and function; if describing a function's job
   needs the word "and", it is that many functions. A concern gets a directory named for it, and the tree
   runs abstract at the top, concrete in the leaves.
   Worry at ~80 to 100 lines and treat ~150 as the ceiling; a file past that is doing too much.
   Split by concern into sibling files, not into many functions in one file. Each file has a sensible
   public/private split: a name another file imports is public (no `_`); only single-file internals carry
   `_`. No file is made of only `_`-private names.
4. **Generic daemon, device-specific jinni.** Generic `core/` code must never name `lmd`, a Klipper init
   path, or any concrete device fact. Those belong to the adapter's jinni, which the daemon delegates to.
5. **Rule of three.** The third copy of a logic block, shape, or constant gets extracted. Duplication is a
   bug. "No premature abstraction" forbids generalizing for one caller; it does not excuse copy-paste.
6. **The printer is never left broken.** Every error path leaves the printer usable; the auto-deactivate
   safety net runs on every op that restarts a core service. No silent excepts: act or report.
7. **A class only when there is real state to hold.** Default to plain functions with data flowing
   through them. A class earns its keep when an instance owns state that changes over its lifetime; a
   class whose methods only take arguments and return results is a module with extra ceremony.
8. **Write less first.** The cheapest code is the code you do not write: question whether it needs to
   exist, prefer stdlib / native / an existing helper, then write the smallest clear solution. A means to
   readability, never code-golf; it never overrides 1 and 2 and never adds "upgrade path" comments.
9. **RULE ZERO: no em-dash or en-dash, anywhere.** Use a comma, colon, semicolon, parentheses, or two
   sentences. A hyphen in a compound word is fine. Enforced by the shared em-dash guard in the gate.

## How to work a change

1. **Understand first.** Read the relevant module and the two docs above. Do not invent architecture; if
   the intent is unclear, ask one specific question and stop.
2. **Scope it to a user story.** "As a [role], I want [capability] so that [value]." If none was given,
   write one and confirm it. Implement only what the story needs: no speculative features, no defensive
   code for cases that cannot happen.
3. **Write the code** to the rules above.
4. **Self-review against engineering-rules.md** before declaring done: the two non-negotiables, separation
   of concerns, file-size, rule of three, typed signatures with no leaking `Any`, no comments except a
   non-obvious why.
5. **Run the gate and make it green:** `bash scripts/check.sh` (em-dash guard, ruff, strict mypy, pytest
   on Python 3.11).
6. **Add a regression test** for the behavior, at the layer that would catch its regression, in the same
   change. It fails on the old behavior and passes on the fix.
7. **Keep the docs current.** If the change alters a boundary, an invariant, or where a concern lives,
   update architecture.md (and the README/CHANGELOG when user-facing).

## Hard constraints

- **Never run git.** The maintainer commits. Leave the tree green and hand over exact commands if a
  git action is needed.
- **Never SSH-mutate a live printer** without explicit per-action authorization. Read-only diagnosis is
  fine; propose any device-changing step and wait for a yes.
- **Never pip the system, Klipper, or Moonraker interpreters.** The daemon's deps live in its venv; plugin
  deps are baked into the package. (See the venv-isolation invariant in architecture.md.)
- **Versioning.** Bump `version.py` and `manifest.json` together (the gate refuses a mismatch) and
  update `tests/api/test_api.py`. The app-side `EXPECTED_DAEMON_VERSION` is generated from `version.py`
  at build time, so it needs no manual sync.
- **Gate must stay green** before any change is considered done.
- **Never weaken a refusal to make an install go through.** The refusal table in
  [doc/internals/install-and-update.md](doc/internals/install-and-update.md) is the printer's contract with the user: a
  package that would leave the printer in a state it would not have accepted at install time is
  refused, and an update goes through exactly the same `settle_refusals()` step as an install. Do not
  add an update-only shortcut, do not catch a refusal to continue anyway, and do not delete a name from
  `DAEMON_SERVICES` (a package on the store keeps requiring it forever).
- **The version floors are floors, never ceilings, and they never guess.** A package declares
  `min_daemon_version`; the daemon declares `MIN_JINNI_VERSION` in `version.py` and serves it on
  `/capabilities`. Only a provably-bad pair is refused: a version that cannot be read is not a refusal.
  Raising `MIN_JINNI_VERSION` strands every printer whose adapter is older, so it is the maintainer's
  call, never a side effect of a change.
- **The diffs are applied to the stock original, never to what is on the printer now.** A plugin's kept
  originals live in its own `patches_orig/`, keyed by the target's full path with a fallback to the old
  bare-name key. Never delete a plugin directory on a path that replaces an existing install: that
  directory holds the only copy of the files the printer needs to get back to stock.

## When you are unsure

Ask one specific question and stop. Do not guess and implement, do not "try something reasonable," and do
not burn a long reasoning loop. The architecture is decided by the maintainer; your job is to implement it
to the rules above.
