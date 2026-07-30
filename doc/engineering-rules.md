# Engineering rules

These are software-engineering rules, not Python rules. They decide whether code is readable and
changeable by people who did not write it. They are language-agnostic on purpose: the same rules govern
the desktop app (TypeScript), the adapters (TypeScript), and the plugins (Python). If you are writing or
reviewing a change here, follow them. If you are an LLM assisting a contributor, treat them as the floor:
the human reviewer enforces them and a PR that breaks them gets sent back.

---

## Why these rules exist: two bounded-context readers

Every rule below serves one goal: keep low the amount of context a reader must hold in their head to make a
safe, local change. The operational measure is **time to a successful edit**: someone with decent fluency
in the language but zero context about this codebase should be able to make a small, correct change with
low effort. Every rule answers to that measure; if a rule and the measure ever seem to disagree, the
measure wins, and you tell the reviewer.

The reason this is the goal is that the code now has two kinds of reader, and both are bounded-context
reasoners:

- a **human** holds only a handful of things in working memory at once;
- an **LLM** has a finite context window whose attention degrades as it fills with material, relevant or
  not.

They pay the same cost in the same currency: the more unrelated material a reader must load to change one
thing, the slower and less safe the change, for either of them. This is the bet the rulebook is built on,
and the design premise of a human-machine team: **lowering human cognitive load and keeping the machine's
working context lean are the same move.** Good locality, honest names, and flat flow pay out in both human
comprehension and machine edit-success, because all three reduce the one shared quantity.

The two readers are not identical, so design to whichever one is the **tighter constraint on each axis**:

- **Within a unit** (one function, one file) the machine is usually tighter: it degrades on large, dense
  blobs and long-range attention faster than an experienced human. So keep units small and flat.
- **Across units** (navigating the repo, following a flow through indirection) the human is tighter: a
  machine can grep the whole tree cheaply, a human cannot. So keep the map navigable, the names honest, and
  indirection low.

Satisfy the tighter reader on each axis and you satisfy both. That is what the rules below encode: small,
flat units (machine-bound) plus concern-directories and domain names (human-bound).

**The direction is not negotiable: human cognitive load is the objective; a lean machine context is the
correlated side effect, never the target.** Optimize for the human and the machine rides along. Invert it,
optimize for the machine, and you drift into machine-pleasing bloat: redundant scaffolding,
over-documentation, structure that exists only to feed retrieval. Write for the human who will maintain
this code; the assistant benefits precisely because the human does.

The rules below are the HOW; this is the WHY. When a rule's letter and its purpose seem to conflict, apply
the purpose.

---

## The two non-negotiables

Two rules sit above all the rest because they decide whether the code is readable to anyone but the
author. Skim past these and the rest of the rulebook is wasted effort.

### 1. Every identifier carries domain meaning

The name's job is to maximise the information handed to a future reader. If a name adds no domain
information, naming the thing bought nothing.

The test: does this name tell the reader what the thing **is** in the domain? Not its type (the
annotation does that), not its position (the parameter list does that), not that it exists (declaring it
does that). What it **is**. If the name does not answer that, rename it.

Worked example, a `line_similarity(a, b)` helper:

- `line_similarity(a, b)` is wrong: `a`/`b` are positional placeholders; the reader scrolls into the body
  to learn which is which.
- `line_similarity(patch, source)` is still wrong: it reads like the whole patch and the whole source
  file, but each argument is a single line. The reader is misled.
- `line_similarity(patch_line, source_line)` is correct: a reader who has never seen the function knows
  instantly which argument is which.

Forbidden regardless of how small the scope is (a short scope is not a licence to be unreadable; the
reader still pays):

- single-character names (`p`, `d`, `e`, `s`, `r`, `f`, `i`, `n`), with one exception: `x`, `y` and `z`
  when they really are coordinates or dimensions. A loop index is not an exception: if the thing being
  counted carries any meaning beyond "how many times round", it gets a real name
  (`for attempt in range(...)`, `for line_number, line in enumerate(...)`);
- positional suffixes (`line_a`/`line_b`, `arg1`/`arg2`, `first`/`second`) when a domain word exists;
- role-free abbreviations (`ev`, `ep`, `pl`, `cb`, `fn`, `tmp`, `val`, `idx` when a better word exists);
- type-only names (`str_`, `arr`, `obj`, `data` when it actually means something specific, `lst`, `dct`).

How to name: ask "what is this in the domain?" and use that word: `plugin`, `manifest`, `endpoint`,
`channel`, `phase`, `progress_event`, `failing_section`, `spool_id`. Comparators use `earlier`/`later` or
domain words, never `a`/`b`.

### 2. Nesting beyond one level is suspicious

Anything more deeply nested than one level inside a function body is suspicious by default. The default
move is to flatten; nesting must justify itself.

Nesting is not only functions inside functions. It includes nested `if`, an `if` inside a
`for`/`while`/comprehension (one conditional inside one iteration is the ceiling), nested ternaries or
conditional expressions, callback or `await` pyramids, and `try` wrapping a body that itself nests.

Why: each indentation level is one more open context the reader must hold. Nesting is the subordinate
clause of natural language; occasionally it is the clearest form, usually it is avoidable complexity.

Standard refactors when you spot depth:

- extract the inner block into a named function (the name is the documentation);
- use early returns / guard clauses to flatten the happy path;
- replace `for` + `if` with a filtered comprehension;
- replace a nested ternary with a small named lookup (a dict keyed by the deciding value).

The escape hatch is rare. Python has a few cases (a `with` block, no early return out of a comprehension)
where flattening is genuinely worse. When you choose to nest, leave a one-line comment saying why the
flat form is worse, so the next reader does not have to rediscover it.

---

## Write less first

The cheapest code is the code you do not write, and the smallest change that solves the problem is usually
the most readable one. Before adding anything, walk this ladder and stop at the first rung that answers the
need:

1. Does it need to exist at all? Drop the feature, the option, the abstraction, the defensive branch for a
   case that cannot happen.
2. Does the standard library already do it? Use it.
3. Is it a native capability of something we already run on? Use that.
4. Is it already a dependency or a helper in this codebase? Reuse it (and once a pattern repeats three
   times, extract it, per the rule of three below).
5. Only then write it, as the smallest solution that is still clear.

This is a means to readability, not a code-golf target. It never overrides the floor: do not collapse logic
into a clever one-liner that breaks the two non-negotiables (a dense nested ternary, single-letter names),
and do not leave "upgrade path" or "TODO" breadcrumb comments (the no-comments rule stands; a real
constraint is the one allowed kind of why-comment). Smaller is better only when it is also clearer; when
minimal and readable disagree, readable wins.

---

## Structure: separation of concerns

Separation of concerns is non-negotiable: one responsibility per module, file, and function. The most
common structural defect is a file that grew by accretion: roughly split, jumbled, and not categorized by
concern, so a reader has to hunt through unrelated code to find the part they need. Do not write one.

- **Directories categorize concerns, from day zero.** A concern gets a directory named for it, and the
  files that belong together live in it (`core/safety/`, `core/uds/`, `api/routes/`). The test: a newcomer
  finds the file they need fast and never has to hunt through a jumbled file. Apply this when you create
  the file, not as a later cleanup. **Test code is still code:** when tests do not live next to the code
  they cover, the test tree mirrors the source tree (`tests/core/packages/` tests `core/packages/`), so a
  test is as findable as the code it guards.

- **The tree runs abstract at the top, concrete in the leaves.** Depth is an abstraction axis, not a
  filing cabinet. The files a reader meets first say *what happens*; each level down says more about
  *how*, until the leaves hold the mechanism. A reader changing the shape of the output should never have
  to walk through the algorithm to find it, and a reader who wants the concept should find it stated
  without the implementation noise. The test: open the top of a directory cold and you learn what it
  does; you visit a leaf only when you actually need that level of detail. A tree that forces
  implementation on a reader first is upside down, whatever its names are.

- **A specific concern gets a room of its own.** A cluster that is *specific*, not general to the layer it
  sits in, does not lie flat among the general siblings: it gets its own directory. The general layer then
  stays uniform (a reader scanning `core/packages/` meets only the shared package-ops vocabulary), and the
  specific cluster is isolated where it belongs (the auto-deactivate recovery flow lives in
  `core/packages/recovery/`, not as three loose files next to `archive.py` and `manifest.py`). The trigger
  is either signal: a concern grows to two or three cohesive files, or one file is enough of an outlier in
  specificity that it reads as out of place among its siblings. Give it the room as soon as the signal
  appears, not in a later cleanup. Name the room for the concern, never for a layer that already exists
  elsewhere (a `safety_net.py` inside a package while `core/safety/` is "the safety net" is the kind of
  name clash that makes a reader guess which layer they are in; rename so each name points at one thing).

- **Generic versus device-specific is a hard separation.** The daemon is a generic on-printer agent.
  Klipper / Moonraker / Snapmaker / `lmd` specifics (concrete service names, init-script paths, restart
  commands) do **not** belong in generic daemon modules; they belong to the adapter and its jinni, which
  the daemon delegates to. A generic file that names a concrete device or service is a defect. See
  [architecture.md](architecture.md) for the boundary and how the jinni supplies the specifics.

- **File-size ceiling.** Start worrying at about 80 to 100 lines. Treat 150 as the ceiling, crossed only
  when there is a genuine reason and splitting would make the code harder to read rather than easier. A
  file past that is almost always doing more than one thing. **Splitting a god file into many small
  functions in the same file does not satisfy this.** Split into sibling files by concern; architecture.md
  maps how the larger modules here are broken up.

- **Rule of three.** First use: inline it. Second use: tolerated, note it. The **third** occurrence of the
  same logic block, shape, or constant is a defect: extract a shared function, helper, or constant.
  Duplication is a bug, not a style preference.

- **No premature abstraction, defined.** The ban is on speculative generality for a single caller (a
  plugin-point, options bag, or generic built for one use). It does **not** license copy-paste once a
  pattern is real. One use: inline. Third use: you must extract. Abstraction earned by repetition is not
  premature. This and the rule of three are two ends of one rule, not a contradiction.

- **Single source of truth across every boundary.** Any shape that crosses a boundary (app to daemon,
  TypeScript to Python, one process to another) is declared once and imported or generated, never
  hand-mirrored. The version is the worked example: `DAEMON_VERSION` in `version.py` is the source, and
  the app derives its expected version from it at build time (generated, not hand-mirrored), so there is
  nothing to drift. Where a mirror is genuinely unavoidable across languages, a test must fail when the
  two diverge.

- **Supporting files for low-value helpers.** Trivial one-line normalizers and adapters aid readability
  but add entropy in large, prominent, contributor-facing files. Relocate them into a context-chosen
  supporting file (a `helpers` or `lib` or `<concept>` module) and keep the named call site. Keep the
  upper layers a contributor meets first low-entropy; the rarely-visited machinery lives deeper. A
  helper sits at the **bottom of the dependency chain**: everything may import it, it imports nothing of
  ours. A "helper" that reaches back into business logic is not a helper, it is business logic filed
  under the wrong name, and it will become an import cycle.

- **Public and private must make sense; no file is all-private.** The `_` prefix means "private to this
  file": used only inside the module that defines it. If another file imports a name, that name is public,
  full stop; it carries no `_`. There is no such thing as a cross-file private. The corollary: a module
  cannot consist only of `_`-private names, because then nothing answers "how do I call this?" When you
  split a file, the call edges that were inside it become inter-file; in the SAME change, promote every
  entry point another file now calls to a public name and keep only the genuine single-file internals
  private. Never let this drift into a later cleanup pass. The split is the test of the boundary: a name
  reaching across files with a `_` means it is misnamed. (Tests are white-box and may reach into a
  module's genuine internals directly from that module; that is the one place a `_`-name is read across
  files, and it needs no re-export shim through a package `__init__`. Import the internal from its home
  module.) This is gated: `scripts/private_import_guard.py` fails the build on any cross-file import of a
  `_`-name in `core/`, `api/`, or `jinni/`, so it is caught mechanically, not by enumeration.

---

## Functions and flow

- **Functional core, isolated side effects.** Internal logic is pure functions. Side effects (the
  filesystem, subprocesses, sockets, HTTP) are isolated at the outermost boundary. A pure core is the part
  that is cheap to test and safe to reason about; do not bloat it.
- **A function does exactly one thing.** The test is the word "and": if describing the job needs it
  ("validates the order **and** totals it **and** emails the customer"), it is that many functions. The
  caller then reads as a list of named steps, which is the documentation.
- **Short functions.** If a function needs a paragraph to explain it, it is two (or more) functions. 40
  lines is the ceiling, matching the app's gated limit; a function that regularly runs longer has failed
  the "and" test above and is telling you so.
- **A class only when there is real state to hold.** Default to plain functions with data flowing through
  them. A class earns its keep when an instance owns state that changes over its lifetime (a live
  connection, an in-progress install, a queue). A class whose methods only take arguments and return
  results is a module with extra ceremony: make it functions. This is the same rule as "as stateless as
  possible", stated where it bites in Python.
- **Edge cases first, canonical path after.** Open with guards for the special, error, and edge cases,
  then fall into the normal path, ordered from the most specific case down to the most general. It makes
  what the function protects against obvious at a glance, and the default case needs the least
  explanation, so it reads last.
- **Constants at the top, before the logic.** A function reads like a proof: state the knowns first. A
  threshold or a surcharge invented halfway down a branch (`if weight > 50: surcharge = 20`) hides both
  the number and its meaning inside a condition. Name it above the logic, then use the name.
- **Iterate declaratively.** A comprehension or a generator says *what* you want; a hand-managed index
  says *how* to get it step by step. Prefer a comprehension for a bounded result, a generator for a large
  or lazy sequence, and a plain `for` when the body does real work. Never a `while` with a
  hand-incremented counter. Recursion suits tree-shaped data and is never a substitute for a data loop:
  Python caps the stack around a thousand frames, so recursing over a data set is a crash waiting for a
  big enough input, not a style choice.
- **Permissive input, strict output.** Be liberal in what you accept, exact in what you return.
- **Idempotency as a design goal.** An operation should be safe to run twice. The daemon's install,
  recover, and teardown paths rely on this.
- **Never block.** Async, non-blocking I/O throughout. A test that waits on a socket, queue, or
  subprocess uses a bounded wait; a hang is worse than a slow test, because a gate that can hang gets
  skipped.
- **Composition over inheritance**, and **as stateless as possible**: push state to the edges.

---

## Resilience: the printer is never left broken

Every error path must leave the printer usable. This is foundational, not a nicety: it is what lets a user
experiment freely and what makes a firmware OTA survivable. The auto-deactivate safety net (a plugin that
breaks a core service is attributed and peeled off so the printer stays up) is the worked example; it must
run on every operation that restarts a core service, not only on recover.

- No silent excepts. An ignored failure is forbidden: act on it or report it (capture the log tail or
  traceback and surface it to the app), never swallow it.
- A diagnosis path may read the device; a mutation path must be deliberate and reversible.

---

## Comments and self-documentation

- **No comments**, with one exception: a single line explaining a genuinely non-obvious **why** (a
  constraint, or why a form that looks wrong is the only correct one). Code that needs a comment to be
  understood is code that needs rewriting; the names and the structure carry the meaning.
- **The urge to write a comment is a signal, and the signal is not "write it".** Wanting to explain
  *what* a line or a block does means a name is lying or the structure is wrong. Rename the thing or pull
  the block into a named function, and the comment becomes unnecessary. Only a *why* survives that test.
- **Listen to the code.** Every line justifies its existence, its form, and its location. A large file is
  telling you it holds multiple concerns: split it. A construct that looks smelly is probably wrong.

---

## RULE ZERO: the em-dash and en-dash are banned

The em-dash (U+2014) and the en-dash (U+2013) are forbidden as punctuation everywhere: source, comments,
docstrings, JSON, Markdown, commit messages, and PR text. Use a comma, colon, semicolon, parentheses, or
two sentences instead. A plain hyphen inside a compound word (`on-printer`, `start-stop-daemon`) is fine;
it is not punctuation. This is enforced by the shared em-dash guard in the gate, so a stray dash is a
build break, not a style note.

---

## How these apply in this repo (Python and FastAPI specifics)

- **Typed signatures throughout.** Every function is annotated; `mypy` runs strict (it is configured in
  `pyproject.toml` and discovered with cwd at the repo root). No `Any` leaking out of a function: narrow
  it or `cast` it at the boundary with a one-line reason.
- **Imports at module top. No magic numbers.** Name the constant when the number means something.
- **The venv-isolation invariant.** The daemon's own dependencies live in its venv. The daemon never pips
  into the system, Klipper, or Moonraker interpreters; plugin Python deps are baked into the package and
  installed offline or symlinked. Overlaying a system interpreter silently breaks Klipper or Moonraker and
  is painful to diagnose. See architecture.md.
- **Commands and live feeds are different transports.** A command that needs a definite result and status
  code is HTTP. State that pushes on change (print state, install progress, plugin logs) rides an
  authenticated websocket. Do not stream a command's result over a side channel, and do not poll for state
  that has a feed. See architecture.md.
- **Every behavior change ships with a regression test** at the layer that would have caught the bug (a
  unit test for pure logic, a fault-injection or integration test for wiring). The test fails on the old
  behavior and passes on the fix, in the same change.
- **Versioning.** Bump `version.py` (`DAEMON_VERSION`) and `manifest.json` together (the gate fails if
  they disagree), and update `tests/api/test_api.py`. The app's expected version is generated from
  `version.py` at build time, so there is no `EXPECTED_DAEMON_VERSION` mirror to keep in sync.

---

## A rule with no gate is a suggestion

The mechanical rules are gated so they cannot drift: `scripts/check.sh` runs the em-dash guard, `ruff`,
strict `mypy`, and `pytest` on Python 3.11 (the device runtime). Run it before every push:

```sh
bash scripts/check.sh
```

The judgment-based rules (naming, nesting, one responsibility, the file-size and rule-of-three smells) are
not machine-checkable; they are the reviewer's job and yours. When you add a new class of defect that
could recur, add a check for it, not just a one-off test.
