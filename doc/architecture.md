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
that one; and streams live install progress and print state to the app.

It is "plugin zero": the adapter bootstraps it over SSH at enrollment (deploy the files, generate a
self-signed cert, seed the access-control list, start it), not through the normal plugin pipeline. Every
request is a bearer token over cert-pinned HTTPS on port 4269.

## The central boundary: generic daemon, device-specific jinni

The single most important design rule here is the separation between generic and device-specific code.

- The **daemon is generic.** It knows about plugins, packages, install phases, services, health, and
  recovery in the abstract. It must not name a concrete device fact: not `lmd`, not a `S60klipper` init
  path, not a Moonraker restart command.
- The **jinni is the device's half**, and it is delegated to. The generic base jinni (`jinni/`, split
  by concern into `base.py` `Jinni`, `klipper.py` `KlipperPrinterJinni`, `inspection.py` the device
  probes, `contracts.py` the typed shapes the interface returns) defines the interface and the path
  contract; the device jinni (for example `bespok3d_jinni` for the Snapmaker U1) ships **with the
  adapter**, not in this repo, and supplies the concrete paths, restart commands, service tokens, and
  control scripts. `jinni/loader.py` is the gate that loads a device jinni and refuses one that does not
  satisfy the contract (a klipper jinni must resolve its path keys AND its klipper/moonraker restart
  commands, failing at load, not first install).

When you need a device-specific value or action, the daemon does not hardcode it; it asks the jinni. If
you find yourself typing a Snapmaker or Klipper specific into a `core/` file, stop: that fact belongs
behind the jinni interface. As of ADR-0029 Part 1 the static coupling is gone: `core/intent.py` and
`core/service_actions.py` name no device path, restart command, or service token. Placement and
instrument classes resolve via `jinni.placement_destination`/`instrument_destination`, restart hooks via
`jinni.restart_command`, the service-action tokens via `jinni.service_action_vocabulary`, and the
display control script via `jinni.startup_control_scripts`. Only the bespok3d-layout conventions stay in
core (the `etc/init.d` autostart wiring and the `var/lib` data dir in `intent.py`) because they name the
daemon's own `$BESPOK3D` tree, not a device. Part 2 (moving every printer-service read and the
permission-to-act judgment behind the jinni) is still pending.

## The transport boundary: HTTP for commands, websockets for live state

This split is intentional and stable.

- **HTTP** carries commands that need a definite request, response, and status code: install, uninstall,
  reconfigure, recover, update-batch, teardown, deactivate, status, capabilities, selfcheck, and the
  access flow. The caller gets one body and one status code.
- **Websockets** carry state that pushes on change: `/ws/print-state`, `/ws/install-progress`,
  `/ws/plugin-log`. They are authenticated by a token query parameter (the bearer middleware is HTTP-only)
  and relay only on change.

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
core/                 install / recover / safety / intent / auth / transport / capabilities ...
  safety/             attribution, health, fixers, decision: the self-heal family
jinni/                generic base jinni (base/klipper/inspection/contracts) + loader; device jinnis live in the adapter repo
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
  `python_deps`, `archive`, `manifest`, `dependencies` (the dep graph and topo sort), `deactivation`, and
  `recovery` (pairs with `core/safety/`). The `__init__` is now essentially the facade: the four op
  wrappers plus `recover` (kept as facade wiring) and `ensure_lmd_control_script` (a jinni-boundary
  outlier). Consolidate the duplicated deactivate/uninstall/guard helpers while extracting.
- **`api/routes/` DONE (from `api/routes.py`, 442 lines).** Thin route registration that delegates to
  core, an `APIRouter` per concern aggregated in `__init__`: `health` (status/capabilities/selfcheck),
  `feeds` (the three live websocket handlers and the `install_hub`), `packages` (install/reconfigure/
  recover/update-batch/uninstall), `lifecycle` (deactivate/teardown), `access` (the request/grant/revoke
  flow). `paths` holds the shared data-root constant. Handlers stay thin.
- **`core/auth/` (from `core/auth.py`, 149 lines).** One security concern per file: keys, roles, labels,
  tokens, identity, and the request/grant/revoke cycle.
- **`core/intent.py` DONE (ADR-0029 Part 1).** The service-action classifier was split out earlier to
  `core/service_actions.py`. Part 1 then moved the device coupling behind the jinni: the placement and
  instrument class maps to `jinni.placement_destination`/`instrument_destination` (bespok3d-layout classes
  on the base `Jinni`, klipper classes on `KlipperPrinterJinni`), the `RESTART_HOOKS` commands to
  `jinni.restart_command` (the four U1 commands now live in the adapter), the classifier's device tokens
  (`lmdctl`/`init.d`/`nginx`) to `jinni.service_action_vocabulary` (the verb regex and klipper/moonraker
  names stay generic in `service_actions.py`), and `ensure_lmd_control_script` to
  `jinni.startup_control_scripts` + a generic `write_startup_control_scripts` writer. `intent.py` keeps
  only the bespok3d-layout service wiring and data-dir convention (its own `$BESPOK3D` tree, no device
  value). Part 2 (printer-service reads + the permission gate) is the remaining ADR-0029 work.
- **`core/printer_comms/` DONE (was the tentative `core/uds/`).** Groups the clients that talk to the
  printer's own running services: `klippy`, `moonraker`, and the shared `frame` transport.
- **`core/safety/fixers/` (from `core/safety/fixers.py`).** One fixer per file with a registry, so new
  failure modes slot in cleanly.
- **`core/safety/health.py` DONE.** The 233-line file split by concern into the `core/safety/probe/`
  package plus two siblings. `probe/` holds the per-service health probes, mirroring `printer_comms/`:
  `reach.py` (the shared low-level reachability primitives `service_get` + `port_listening`, the foundation
  any new probe builds on), `klipper.py` (`klipper_healthy`, `klippy_socket_path`), `moonraker.py`
  (`MoonrakerInfo`, `probe_moonraker`, `moonraker_healthy`). Alongside it: `config_links.py` (the
  dead-symlink self-heal on the bespok3d include dirs: `prune_dead_config_links` + `restart_moonraker`) and
  `restart_batch.py` (the deferred-restart batch + verify cycle: `run_restart_batch`).
- **`core/live/` DONE (absorbed `core/log_capture.py`).** The websocket push-on-change sources:
  `install_progress`, `print_state`, and `log_capture`.

Each extraction is its own reviewed step: gate green to start, write the failing test first, extract, gate
green, stop for review. The decomposition is tracked in the project's cleanup ledger.
