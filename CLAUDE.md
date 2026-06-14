# bespok3d-daemon: instructions for AI assistants

You are working in the Bespok3d daemon, the on-printer service for a Klipper plugin manager. This file is
the contract for any LLM or agent that touches this repo. Contributors here often use AI assistance, so
these rules and the design intent are written down and enforced in the gate, not left implicit. Read them
and uphold them; the human reviewer rejects a PR that ignores them.

If you are a non-Claude tool, `AGENTS.md` points you here.

## Read these first

- [doc/engineering-rules.md](doc/engineering-rules.md): the rules every change follows. These are
  software-engineering rules, not Python rules; they apply identically across the wider Bespok3d codebase.
  Read it fully before writing code.
- [doc/architecture.md](doc/architecture.md): what the daemon is, the generic-versus-device boundary, the
  HTTP-versus-websocket boundary, the invariants, and where each concern lives (and is moving to).
- [README.md](README.md) for build/version/release mechanics; [CONTRIBUTING.md](CONTRIBUTING.md) for the
  contribution flow.

## The non-negotiables (the floor; full treatment in engineering-rules.md)

1. **Every identifier carries domain meaning.** A name says what the thing *is* in the domain, never its
   type, position, or a role-free abbreviation. No `a`/`b`, `tmp`, `data`, single letters.
2. **Nesting beyond one level is suspicious.** Flatten by default: guard clauses, early returns, extracted
   named functions, a named lookup instead of a nested ternary. When you must nest, comment why.
3. **Separation of concerns.** One responsibility per file and function. A concern gets a directory named
   for it. Worry at ~80 to 100 lines and treat ~150 as the ceiling; a file past that is doing too much.
   Split by concern into sibling files, not into many functions in one file.
4. **Generic daemon, device-specific jinni.** Generic `core/` code must never name `lmd`, a Klipper init
   path, or any concrete device fact. Those belong to the adapter's jinni, which the daemon delegates to.
5. **Rule of three.** The third copy of a logic block, shape, or constant gets extracted. Duplication is a
   bug. "No premature abstraction" forbids generalizing for one caller; it does not excuse copy-paste.
6. **The printer is never left broken.** Every error path leaves the printer usable; the auto-deactivate
   safety net runs on every op that restarts a core service. No silent excepts: act or report.
7. **RULE ZERO: no em-dash or en-dash, anywhere.** Use a comma, colon, semicolon, parentheses, or two
   sentences. A hyphen in a compound word is fine. Enforced by `scripts/em_dash_guard.py` in the gate.

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
- **Versioning.** Bump `version.py` and `manifest.json` together (the pack refuses a mismatch); keep the
  app-side `EXPECTED_DAEMON_VERSION` and `tests/test_api.py` in sync.
- **Gate must stay green** before any change is considered done.

## When you are unsure

Ask one specific question and stop. Do not guess and implement, do not "try something reasonable," and do
not burn a long reasoning loop. The architecture is decided by the maintainer; your job is to implement it
to the rules above.
