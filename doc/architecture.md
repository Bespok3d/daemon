# Architecture and design intent

This is the internal map of the daemon: what it is, the boundaries that hold it together, where code
lives, and where the in-progress decomposition is headed. Read it before adding a module, so a new
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

The single most important design rule here is the separation between generic and device-specific code
(ADR-0037).

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
question and gets a serializable answer. If you find yourself typing a Snapmaker or Klipper specific
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
`jinni/protocol.py CONTRACT_VERBS`): resolve a placement or instrument CLASS to a path
(`placement_destination` / `instrument_destination`), resolve a restart HOOK to a command
(`restart_command`), render a managed-service script (`render_service_script`), report capability flags
and target facts (`capability_flags` / `paths` / `capabilities_report`), classify how each generated
start command acts on the device (`classify_commands`), report the device's health verdict (`health`),
report what is blocked right now (`blocked_actions`), and stream the blocked-action set on change
(`subscribe_blocked_actions`). The daemon builds its logic ON these answers; it never reaches in for the
device knowledge behind them.

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
token verbatim and deactivates nothing, and the app localizes it. The device fact (the broker, port
1883) lives behind the jinni; the daemon carries only the token.

### Where the device half lives now

The retired model had the daemon import and subclass a live device object (`as_klipper_printer`, a
`ServiceActionVocabulary` the daemon string-matched, a `permissions()` snapshot). That is gone. The
device implementation, including the shared Klipper/Moonraker actuation, lives in the jinni package
(`jinni/`), which the adapter's device jinni extends and the daemon parents as a process. Inside that
package the jinni still composes its concerns as a small class tier, faceted one room per concern:
`Jinni` (`base.py`, a generic linux box) from `Layout` / `Realization` / `Facts` / `Probing`, then
`KlipperPrinterJinni` (`klipper.py`) adding the klipper facets (`KlipperRealization` / `KlipperFacts` /
`KlipperProbing` / `KlipperHealth`), with `inspection.py` and `health.py` holding the probe and
health-verdict implementations, `contracts.py` the boundary shapes, `loader.py` the strict-output gate
(it refuses a jinni that cannot resolve its path keys or, for a klipper jinni, its klipper/moonraker
restart commands), and `protocol.py` / `service.py` / `printer_comms/` the process and wire. The device
jinni (`bespok3d_jinni`, in the adapter repo) supplies only the concrete paths, restart commands,
control scripts, and hardware specifics. That class tier is the JINNI's internal reuse; the daemon never
sees it, it sees the socket.

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
  it (`pack.sh` enforces equality), and the app-side `EXPECTED_DAEMON_VERSION` plus `tests/api/test_api.py`
  track it.
- **Auth on every route** except the single unauthenticated `POST /access/request`. Token comparison is
  constant-time.

## Layout

Natural Python layout at the repo root; `scripts/pack.sh` maps the deployable subset into a `.b3`.

```
version.py            DAEMON_VERSION, the version source of truth
daemon.py             entrypoint
api/                  FastAPI app, routes, middleware, schemas
core/                 install / recover / safety / intent / auth / capabilities ...
  jinni_client/       the single seam to the jinni: the verbs, the socket transport, the supervisor
  live/               websocket push-on-change sources (install_progress, print_state, log_capture)
  safety/             attribution, fixers, decision, restart_batch: the self-heal family
jinni/                the jinni as a parented PROCESS: the base/klipper tier faceted by concern
                      (layout/realization/facts/probing/health, inspection, contracts), loader, plus
                      protocol/service/printer_comms (the wire); device jinnis ship in the adapter repo
S99bespok3d           boot hook
s10bespok3d-daemon    autostart script
wheels/               prebuilt offline runtime deps (pgpy)
tests/                test suite (not packed); mirrors the source tree (tests/core/packages/, tests/api/, ...)
scripts/              check.sh, pack.sh, generate-atom.mjs, test-daemon-docker.sh (not packed)
doc/                  README + CHANGELOG (shipped in the .b3); this file + engineering-rules (not shipped)
```

## Decomposition in progress (the concern-directory target)

The daemon is mid-reorganization from "split and jumbled" into directories named for their concern. The
rule for new code is to land it in the right concern, not to grow a god file. The target for the largest
offenders:

- **`core/packages/` (from `core/packages.py`, 1441 lines).** The `__init__` keeps a thin public facade
  (the API the routes import) and owns the plugin root, injecting it into the worker modules; the rest
  splits by concern: `errors`, `user_vars`, `placement` (the symlink/dir/mode family), `patches`,
  `templates`, `services`, `installer` (the install/reconfigure/update-batch family + its shared phase
  runner), `uninstaller` (the uninstall family), `lifecycle` (deactivate/teardown), `print_guard`,
  `python_deps`, `archive`, `manifest`, `dependencies` (the dep graph and topo sort), `start_commands`
  (run the start commands, defer core-service restarts to a batch off the jinni's `CommandEffect`),
  `deactivation`, and `recovery` (pairs with `core/safety/`). The `__init__` is now essentially the
  facade: the four op wrappers plus `recover` (kept as facade wiring). Consolidate the duplicated
  deactivate/uninstall/guard helpers while extracting.
- **`api/routes/` DONE (from `api/routes.py`, 442 lines).** Thin route registration that delegates to
  core, an `APIRouter` per concern aggregated in `__init__`: `health` (status/capabilities/selfcheck),
  `feeds` (the three live websocket handlers and the `install_hub`), `packages` (install/reconfigure/
  recover/update-batch/uninstall), `lifecycle` (deactivate/teardown), `access` (the request/grant/revoke
  flow). `paths` holds the shared data-root constant. Handlers stay thin.
- **`core/auth/` (from `core/auth.py`, 149 lines).** One security concern per file: keys, roles, labels,
  tokens, identity, and the request/grant/revoke cycle.
- **`core/intent.py` DONE (ADR-0026, then ADR-0037).** It translates the intent-based install block
  (`place` / `instrument` / `service` / `restart`) into the mechanism operations the executor runs,
  naming no device value: a placement or instrument resolves its CLASS via
  `jinni_client.placement_destination`/`instrument_destination`, and a restart resolves its HOOK via
  `jinni_client.restart_command`. Command classification (`classify_commands`) and writing the jinni's
  own startup control scripts moved INTO the jinni process (the verb plus `jinni/service.py`), so the
  daemon no longer owns a service-action vocabulary or a control-script writer. `intent.py` keeps only
  the bespok3d-layout service wiring and the `var/lib` data-dir convention (its own `$BESPOK3D` tree, no
  device value).
- **`jinni/printer_comms/` DONE (ADR-0029 Part 2 P6; was `core/printer_comms/`, the tentative
  `core/uds/`).** Groups the clients that talk to the printer's own running services: `klippy`,
  `moonraker`, and the shared `frame` transport. Talking to the printer's OWN software is the device's
  realm, so these live with the jinni; generic `core/` reaches them through the jinni boundary
  (`from jinni.printer_comms import ...`).
- **`core/safety/fixers/` (from `core/safety/fixers.py`).** One fixer per file with a registry, so new
  failure modes slot in cleanly.
- **`core/safety/health.py` DONE, then `probe/` moved behind the jinni (ADR-0029 Part 2 P7+P8).** The
  233-line file first split into a `core/safety/probe/` package plus two siblings. Part 2 then moved the
  whole printer-service-health concern onto the jinni: the low-level reachability (`reach.py`'s
  `service_get` + `port_listening`) became overridable base-`Jinni` methods (P7, impl in
  `jinni/inspection.py`), and the per-service verdicts (`klipper_healthy`, `moonraker_healthy`,
  `probe_moonraker`) became `KlipperHealth` methods that assemble the boundary `DeviceHealth` /
  `ServiceHealth` report (`jinni/contracts.py`), with `MoonrakerInfo` an internal type in
  `jinni/health.py`; `core/safety/probe/` is deleted. The safety net asks for the report through the
  seam, `jinni_client.health()` (ADR-0037), never an imported device object. What stays in
  `core/safety/`: the brain (attribution / decision / fixers / net) plus `config_links.py` (the
  dead-symlink self-heal on the bespok3d include dirs: `prune_dead_config_links` + `restart_moonraker`)
  and `restart_batch.py` (the deferred-restart batch + verify cycle: `run_restart_batch`).
- **`core/live/` DONE (absorbed `core/log_capture.py`).** The websocket push-on-change sources:
  `install_progress`, `print_state`, and `log_capture`. `print_state` stays device-free: `app_frame`
  shapes the jinni's blocked-action token set into the `/ws/print-state` frame, and the route
  (`api/routes/feeds.py`) relays the `subscribe_blocked_actions` stream verbatim (ADR-0037), so the
  daemon classifies no print state.

Each extraction is its own reviewed step: gate green to start, write the failing test first, extract, gate
green, stop for review. The decomposition is tracked in the project's cleanup ledger.
