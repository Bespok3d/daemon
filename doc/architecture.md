# Architecture and design intent

This is the internal map of the daemon: what it is, the boundaries that hold it together, and where
each concern lives. Read it before adding a module, so a new
concern lands in the right place instead of growing an existing file. The user-facing overview is
[README.md](README.md); the rules every change follows are [engineering-rules.md](engineering-rules.md).

## What the daemon is

The daemon is the one piece of Bespok3d that runs on the printer. The desktop app, the adapter, and the
plugins all talk to it. It installs, updates, reconfigures, and removes plugins from `.b3` packages;
reports the printer's capabilities and firmware; refuses any operation that would restart a service
mid-print; self-heals by attributing a broken core service to the offending plugin and deactivating only
that one; and streams live install progress and the printer's blocked-action set to the app. It runs
generic and delegates every device-realm action to the adapter's jinni, a child process it parents (see
the central boundary below).

It is "plugin zero": the adapter bootstraps it over SSH at enrollment (deploy the files, generate a
self-signed cert, seed the access-control list, start it), not through the normal plugin pipeline. Every
request is a bearer token over cert-pinned HTTPS on port 4269.

## The central boundary: daemon orchestrates, jinni actuates

The single most important design rule here is the separation between generic and device-specific code.

- The **daemon is generic and ORCHESTRATES.** It knows plugins, packages, install phases, services,
  health, and recovery in the abstract: it unpacks and places files in the bespok3d tree, applies
  patches, sequences, resolves the dependency graph, groups and dedupes restarts (five plugins asking
  to restart one service become a single ask), drives the safety net, and reports to the app. It must
  not name a concrete device fact (not `lmd`, not a `S60klipper` init path, not a Moonraker restart
  command), and it never classifies a command or names a service.
- The **jinni is the device's half and ACTUATES.** It performs the one device-realm action the daemon
  asks for and returns the result: resolving a destination class to a real path, restarting the
  services the daemon already grouped, fetching a stock file for the daemon to patch, and judging the
  live device (is a print running, is the printer healthy). It ships **with the adapter**, not in this
  repo.

When the daemon needs a device value or action it does not hardcode it; it asks the jinni a semantic
question and gets a serializable answer. If you find yourself typing a vendor or Klipper specific
into a `core/` file, stop: that fact belongs behind the jinni.

### The jinni is a separate process behind one seam

The boundary is a data contract, not an object graph: no live jinni object crosses it. On the printer
the daemon spawns and parents the jinni as a child process (`api/__init__.py` lifespan calls
`jinni_client.start_jinni`, gated on being on the printer); the child runs `python -m jinni <socket>`
(`jinni/service.py`), loads the adapter's device jinni, and answers framed-JSON verb calls over a Unix
socket. In dev, with no adapter jinni present, the seam stays in-process against a `GenericJinni`; the
verbs are identical either way.

Every generic `core/` module reaches the jinni through exactly one door, `core/jinni_client/`, plus the
leaf contract shapes in `jinni.contracts` (the serializable values that cross). Nothing else under
`jinni/` (not a tier, not the loader, not the loopback probes) may be imported from `core/`, enforced
mechanically by `scripts/generic_daemon_guard.py`, the in-process equivalent of a process boundary's
physical enforcement. The supervisor (`core/jinni_client/supervisor.py`) keeps a single-instance,
daemon-parented lifecycle: it recycles an orphaned jinni before spawning a fresh one (kill before
respawn, never two), retries a child that fails to serve with bounded backoff, and version-checks the
peer at the handshake (`PROTOCOL_VERSION`, `jinni/protocol.py`), refusing an incompatible adapter with
an "update the adapter" error rather than misbehaving.

### The contract (the verbs)

The verbs are the whole surface the daemon may call (`core/jinni_client/__init__.py`, closed set in
`protocol/wire.py CONTRACT_VERBS`). Read/resolve verbs: resolve a placement or instrument CLASS to a
path (`placement_destination` / `instrument_destination`), resolve a restart HOOK to a command
(`restart_command`), render a managed-service script (`render_service_script`), report capability flags
and target facts (`capability_flags` / `paths` / `capabilities_report`), classify how each generated
start command acts on the device (`classify_commands`), report the device's health verdict (`health`),
report what is blocked right now (`blocked_actions`), stream the blocked-action set on change
(`subscribe_blocked_actions`), report the kernel's out-of-memory evidence for the constrained-board
safety net (`oom_report`), and fetch a stock file for the daemon to patch (`fetch`). ACTUATION
verbs (the daemon resolves and sequences, the jinni mutates the device): run a plugin's
start/restart/stop commands (`run_actions`), symlink placed files and site-package links into the
system (`wire`) and remove them (`unwire`), write a patched (or restored) source back (`write_files`),
and the config-include unwire (`remove_bespok3d_includes` / `prune_bespok3d_config_dir` /
`prune_dead_config_links`). Actuation verbs serialize through one queue on the jinni and run off its
event loop, so a long restart never blocks the concurrent reads or streams; as it wires, the jinni
records each reversion in the plugin's `wiring.json` (the escape-hatch record). The daemon builds its
logic ON these answers and mutates only its own `$BESPOK3D` tree; it never reaches in for the device
knowledge behind them, and it actuates no device file itself. Because `write_files` and `fetch` carry
whole device files (a patched Klipper source, several at once on a restore), the framed socket caps a
message at `frame.MAX_FRAME_BYTES` (16 MiB), well above asyncio's 64 KiB `readuntil` default: a frame
past that default overran and the jinni dropped the reply unanswered ("no reply for write_files").

### Worked example: the print guard

The print guard is the proof that the daemon classifies nothing about printing. The vocabulary is the
jinni's, as machine TOKENS (`jinni.contracts`: `RESTART_KLIPPER` / `RESTART_MOONRAKER` /
`RESTART_DISPLAY`): `blocked_actions()` is the set blocked right now (a running print forbids restarting
Klipper, Moonraker, or the display), and `classify_commands()` tags each command with the
`CommandEffect.blocking_token` it would trigger. The guard (`core/packages/print_guard.py`) is then pure
set membership: map the op to its required tokens, refuse if any is in the live blocked set, raise
`BlockedActionError`. `api/__init__.py` renders that as `409 {"error": "blocked", "blocked_actions":
[...]}`, tokens never prose, and the app localizes each token to a lock reason. The live UI lock rides
the same tokens: `/ws/print-state` is a dumb relay (`api/routes/feeds.py`) over the streaming
`subscribe-blocked-actions` verb, shaped by `core/live/print_state.py app_frame` into
`{"blocked_actions": [...]}`. The jinni pushes on change (it subscribes to Klipper's print_stats); the
daemon forwards verbatim and reads nothing.

### Worked example: the safety-net diagnosis

The safety net judges a `DeviceHealth` report the jinni fills in (`health()`), asking one semantic
question ("is the device healthy?") instead of probing each service or naming a port. When a failure has
a NON-plugin cause the jinni knows (the U1's stock MQTT broker is down, say), the jinni sets
`DeviceHealth.diagnosis` to a machine TOKEN; `core/safety/fixers.py device_infrastructure` relays the
token verbatim and deactivates nothing, and the app localizes it. The device fact (the broker, port 1883) lives behind the jinni; the daemon carries only the token.

### Where the device half lives: a separate app over a socket

The daemon and the jinni are TWO separate apps that communicate over a Unix socket; they share NOTHING
but the protocol. The daemon repo ships its orchestration (`core/`, `api/`) and the `protocol` package,
and nothing else. The jinni runtime is its own app, `adapters/klipper-jinni/` (the `jinni` package: the
generic `Jinni` base + the klipper tier `KlipperPrinterJinni` faceted one room per concern,
`klippy`/`moonraker` comms, klipper health/probing, `KLIPPER_PATH_KEYS`, the port constants, the
loader, and `service.py` / `__main__.py` / the `klipper_vocab` service-and-token vocabulary). A device
adapter (`adapters/snapmaker-u1/`, `bespok3d_jinni`) extends it with concrete paths, restart commands,
control scripts, and hardware specifics. The jinni imports `protocol` (the one allowed crossing); the
daemon imports nothing of the jinni.

The seam is `core/jinni_client`: it imports only `protocol` and reaches the jinni over the socket
(`supervisor.py` spawns `python -m jinni`). For the in-process transport (dev / tests) the jinni is
INJECTED, never imported, so the daemon process and its test suite are free of the jinni runtime. Each
side has its own gate: `daemon/scripts/check.sh` (tests against duck-typed fakes that answer the
protocol verbs), `adapters/klipper-jinni/scripts/check.sh` (the jinni alone, plus the daemon-with-jinni
together tests under `tests/together/`), and `adapters/snapmaker-u1/scripts/check.sh`. The law is gated:
`generic_daemon_guard.py` fails if any `core/` file imports `jinni.*`, or if the `protocol` contract
defines a device-vocabulary string constant.

Only the bespok3d-layout conventions stay in core (the `etc/init.d` autostart wiring and the `var/lib`
data dir in `core/intent.py`), because they name the daemon's own `$BESPOK3D` tree, not a device. The
daemon asks; the jinni answers.

## The transport boundary: HTTP for commands, websockets for live state

This split is intentional and stable.

- **HTTP** carries commands that need a definite request, response, and status code: install, uninstall,
  reconfigure, recover, update-batch, teardown, deactivate, status, capabilities, selfcheck, and the
  access flow. The caller gets one body and one status code.
- **Websockets** carry state that pushes on change: `/ws/print-state` (the jinni's blocked-action token
  set, relayed verbatim), `/ws/install-progress`, `/ws/plugin-log`. They are authenticated by a token
  query parameter (the bearer middleware is HTTP-only) and relay only on change.

Do not stream a command's result over a side channel, and do not poll for state that already has a feed.

## Invariants (do not break these)

- **The printer is never left broken.** Every error path leaves the printer usable. The auto-deactivate
  safety net runs on every operation that restarts a core service.
- **Venv isolation.** The daemon's dependencies live in its own venv. It never pips into the system,
  Klipper, or Moonraker interpreters. A plugin's Python deps are baked into its package and installed
  offline (its own venv) or symlinked into the target interpreter's site-packages (a Klipper/Moonraker
  extra), never installed live on the printer.
- **Version single-source.** `version.py` `DAEMON_VERSION` is the source of truth. `manifest.json` mirrors
  it (`tests/test_manifest_version.py` enforces equality), and `tests/api/test_api.py` tracks it. The
  app derives its expected version from `version.py` at build time (generated, not hand-mirrored), so
  there is no `EXPECTED_DAEMON_VERSION` constant to keep in sync.
- **Auth on every route** except the single unauthenticated `POST /access/request`. Token comparison is
  constant-time.

## Layout

Natural Python layout at the repo root. The daemon is plugin zero: it ships as a `.b3` with
the same shape and the same signature as any plugin, and the single difference is that the adapter puts
it on the printer at enrollment instead of the plugin pipeline installing it. `scripts/stage-package.sh`
maps the deployable subset into the plugin source shape (`manifest.json` + `files/` + `doc/`) that the
org-wide `b3-builder` Action packs, stamps and signs.

```
version.py            DAEMON_VERSION, the version source of truth
daemon.py             entrypoint
api/                  FastAPI app, routes, middleware, schemas
core/                 install / recover / safety / intent / auth / capabilities ...
  jinni_client/       the single seam to the jinni: the verbs, the socket transport, the supervisor
  live/               websocket push-on-change sources (install_progress, print_state, log_capture)
  safety/             attribution, fixers, decision, restart_batch: the self-heal family
protocol/             the ONE module the daemon and the jinni both import: contract dataclasses
                      (contracts), the wire format (wire), the 0x03 framed transport (frame)
S99bespok3d           boot hook
s10bespok3d-daemon    autostart script
requirements.txt      runtime deps, and the ADR-0036 declaration b3-builder bakes into wheels
tests/                test suite (not packed); mirrors the source tree (tests/core/packages/, tests/api/, ...)
scripts/              check.sh, stage-package.sh, test-daemon-docker.sh (not packed)
doc/                  README + CHANGELOG (shipped in the .b3); this file, engineering-rules,
                      story-obligations and doc/internals/ (contributor docs, not shipped)
```

## Where each concern lives

New code lands in the right concern, never in a growing god file, and never names a device fact in
`core/`. The top-level split:

- **`core/packages/`** owns the plugin lifecycle: a thin public facade in `__init__` over worker modules
  split by concern (`placement`, `patches`, `templates`, `services`, `installer`, `updater`,
  `uninstaller`, `lifecycle`, `print_guard`, `python_deps`, `archive`, `manifest`, `dependencies`,
  `start_commands`, `deactivation`, `recovery`).
  What the printer will and will not accept, and how a patch reaches a device file, are written up
  separately: [install-and-update.md](internals/install-and-update.md) (the refusal table, the two version floors,
  what a refused update leaves behind) and [patch-pipeline.md](internals/patch-pipeline.md) (the stock baseline,
  how it is keyed, patch handover).
- **`api/routes/`** is thin route registration that delegates to core, one `APIRouter` per concern
  aggregated in `__init__`: `health`, `feeds` (the live websocket handlers), `plugins`, `packages`,
  `lifecycle`, `access`. Handlers stay thin; the shared data-root constant lives in `core/data_root.py`.
- **`core/intent.py`** translates the intent-based install block (`place` / `instrument` / `service` /
  `restart`) into mechanism operations, naming no device value: a placement or instrument resolves its
  CLASS through the jinni, and a restart resolves its HOOK through the jinni. It keeps only the
  bespok3d-layout service wiring and the `var/lib` data-dir convention (its own `$BESPOK3D` tree).
- **`core/safety/`** is the self-heal family (`decision`, `attribution`, `fixers`, `restart_batch`). It
  is generic and names no service: it maps a jinni-reported failure signal to the culprit PLUGIN via its
  own placement index, decides to deactivate, and orchestrates the restart and re-verify. It reads no
  device log and authors no Klipper/Moonraker text; the health verdict and log parsing are the jinni's.
- **`core/live/`** holds the websocket push-on-change sources (`install_progress`, `print_state`,
  `log_capture`). `print_state` stays device-free: `app_frame` shapes the jinni's blocked-action token
  set into the `/ws/print-state` frame, and the route relays the `subscribe_blocked_actions` stream
  verbatim, so the daemon classifies no print state.

Each change is its own reviewed step: gate green to start, write the failing test first, make the
change, gate green, stop for review.
