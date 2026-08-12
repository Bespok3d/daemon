# Changelog

## 0.12.25

Putting the plugins back after a firmware update no longer switches off a plugin whose files another
plugin had edited on the printer. A plugin that writes into another one's web interface leaves that
file different from what the package it came in recorded, and that was read as a broken plugin and
switched off. The plugin is now put back and left running, and the files that differ are reported, so
the app can offer to install it fresh instead of the user finding it gone. Installing and updating
still refuse a package whose files do not match what was signed: there the difference means the
package itself is wrong.

Putting the plugins back also says where it is now. It reports its list and each plugin as it
finishes on the same feed an install reports on, so the wait shows plugins going past instead of
nothing.

The daemon's start-up script checks that a process really is the daemon before it signals it. The
file holding the daemon's process number survives a reboot, and after one that number belongs to
whatever the printer started next.

## 0.12.24

The daemon and the jinni have to be a matched pair, and the daemon now checks before it installs or
changes a plugin rather than finding out afterwards. It refuses with which of the two is too old, the
version it needs and the version it found, so the app can say what to update instead of just saying
no. A version it cannot read is not treated as too old.

When a plugin stops the printer coming back up, the daemon switches plugins off until it does. It
could switch off itself or the jinni in the process, which left the printer running but no longer
reachable by Bespok3d, and nothing on the printer able to put the daemon back. Both are now left
alone.

A daemon is published by a `daemon-v*` tag now, and by nothing else. Until now any push to main that
touched the daemon source built a package and registered it in the org index, which offered every
enrolled printer a daemon built from whatever main happened to hold at that moment, work in progress
included. Tagging is the maintainer saying which tree is the release, and it matches how the jinni
already releases.

The run is refused before the build if the number in the tag and `DAEMON_VERSION` disagree, so a tag
can never publish a package stamped with a different number.

## 0.12.23

The daemon's Python dependencies now travel inside the package. They are downloaded as aarch64 wheels
when the package is built and packed into it, so installing the daemon on a printer needs no network
beyond the app that is already talking to it. Until now the package carried no wheels and the printer
fetched them from pypi.org at enrollment, which failed on any printer whose network only opens SSH.

The one dependency this repo used to carry by hand, pgpy, is gone. No daemon code has imported it for
some time; the wheel and the two doc lines calling it a shipped runtime dependency went with it.

`requirements.txt` now also names pydantic and starlette, which the daemon imports directly and had
been getting only as dependencies of fastapi.

The release workflow now carries the step that registers the daemon in the org index, so no one has to
remember it by hand. It runs on a push to main, the same trigger every plugin repo registers on: the
daemon is plugin zero here too.

## 0.12.22

The self-check was split into a package of its own and package repair was added.

There is no 0.12.21. The version went from 0.12.20 straight to 0.12.22, and no tree was ever released
as 0.12.21.

## 0.12.20

The `-dev` suffix is gone from the version number. Every release up to `0.12.19-dev` carried it,
including the published ones, which said "unreleased" about software that was on printers. From
here the daemon is plain semantic versioning and nothing else. No behaviour changed with this
number; the entries below keep the suffix because that is what those releases were called.

Anything declaring a `min_daemon_version` lost the suffix at the same time, so a constraint that
read `0.10.1-dev` now reads `0.10.1`. No printer changes behaviour because of it: the app reads only
the numeric release when it compares a daemon against a constraint and ignores everything after the
dash, so a printer still running a `-dev` daemon satisfies exactly what it satisfied before.

## 0.12.18-dev

Out-of-memory detection for the constrained-board safety net. A new
read-only `GET /oom` reports whether the kernel's OOM killer has fired, its most recent victim, and
the cumulative kill count a client dedupes on. The jinni reads /proc/vmstat and the kernel ring
buffer; the daemon relays a machine token (`oom-kill`) the app localizes plus the victim
line. Detection only: the daemon prevents no OOM here. Whether the victim was a core print service or
a plugin is NOT classified (the victim comm is `python3` for the python services, so a comm match
cannot tell them apart; that verdict is a follow-up for when real hardware exists). Preventing OOM
(an oom_score floor, a print-versus-plugin coexistence policy) is deferred until the real 512MB board
and firmware exist to measure against. Device-unverified (no 512MB
hardware yet); logic is unit-tested on both sides.

## 0.12.17-dev

Install-time `require` enforcement. Installing a plugin whose `require`d
service is provided by no installed, non-deactivated plugin is now refused up front with a clear
`RequirementError` (mapped to a 409 the app localizes), instead of half-applying and failing later.
The check runs on both the single install and the batched "install selected"; in a batch a sibling
package can satisfy the requirement (providers are applied before their dependents), mirroring the
existing conflict gate. OTA recover's own precondition skip is unchanged. Every shipping plugin
declares `require: []`, so the gate is inert for them and fires only for the VPN plugins that need
`tun`.

## 0.12.16-dev

The kernel-module OTA autofixer. After a firmware update bumps the
kernel, a plugin's `.ko` no longer matches, and the daemon now names that failure precisely instead
of a generic "install phase failed", so a stale module deactivates cleanly and the printer keeps
working.

- **`kernel` capability fact + `vermagic` variant dimension.** The jinni reports the running kernel's
  release and version magic (the `kernel` fact, read from a loaded module via `modinfo`: the ground
  truth a `.ko` is built against, richer than `uname -r`), and `vermagic` joins the variant
  dimensions in `conditions.py` as the finer key for a module whose ABI differs between two kernels
  that share a release. Full contract dance: the `KernelInfo` schema, the TS wire mirror, the
  regenerated contract fixture, and the fakes.
- **Load-failure classifier + `kernel_module_failure` fixer.** When a kernel-module load
  fails, the jinni classifies it from the kernel ring buffer and emits a
  `kernel-module:vermagic-mismatch` token; the daemon relays it through the safety net's one
  attribution brain (a new `kernel_module_failure` fixer) so the plugin deactivates with that token
  as its reason and its dependents skip, exactly as the OTA recover path already deactivated a broken
  plugin. The classifier keys on the kernel's actual version-magic verdict, never a bare non-zero
  load (a module that loads then misbehaves is a different cause, and a vermagic verdict is the honest
  limit of what a load check can prove); classification is best-effort, so a dead-jinni round-trip degrades to the generic reason
  rather than aborting the install.

## 0.12.15-dev

The kernel-module mechanism gets its first real specimen (the `tun-module` plugin), and two guards
the specimen exposed.

- **`kernel_release` variant dimension.** A `.ko` is cross-built per kernel, so a `kernel-module`
  place entry now selects on `when.kernel_release` (the running kernel's `uname -r`, an exact-match
  dimension in `conditions.py`). The jinni reports it via a new `kernel_release` fact (base tier
  `unknown`; the U1 reads `uname -r`), kept in `variant_facts` only, not the capabilities report
  (the richer `kernel`/`vermagic` capability comes later). A box whose kernel matches no
  variant places no module, which fails closed.
- **`install.kmodule` must load a placed `.ko`.** `normalize_install` now refuses a manifest whose
  `install.kmodule.module` names no `kernel-module` place entry: the loader insmods only from
  `$BESPOK3D/lib/modules/`, so an unplaced module would fail insmod (a safe deactivate). The name is
  variant-stable, so the check holds regardless of which kernel a printer resolves.

## 0.12.14-dev

Kernel modules become a first-class plugin artifact (the mechanism). A plugin can now
place a cross-built `.ko` and have the daemon load it, so a driver like `tun` (for the VPN plugins)
ships the way any other file does.

- **`kernel-module` destination class** places a `.ko` under `$BESPOK3D/lib/modules/`, and a new
  **`install.kmodule`** section declares the module, its device nodes (`/dev/net/tun c 10 200`), and
  whether to load it now. The daemon asks the jinni to render an s05 loader script (it owns
  insmod/mknod/rmmod) and wires it into the autostart dir BEFORE the s65 services, so a
  service that needs the module finds it already loaded. The whole feature is gated on a new
  `kernel-modules` capability flag; the U1 advertises it.
- The module load runs immediately in its own install phase, not through the deferred core-service
  restart batch: a kernel-module load restarts no core service and must precede any service that
  needs it. A load that fails deactivates the plugin, so the printer is never left half-loaded.
- New jinni verbs: `render_module_script` (the loader) and `device_node_present` (a cheap read that
  checks a loaded module's outcome, e.g. `/dev/net/tun`). New `core/packages/kmodules.py`; the
  init-script write mechanic is shared with managed services in `core/packages/init_scripts.py`.

## 0.12.13-dev

The variant engine: a manifest place/instrument entry may carry `variants: [{ when, src|diff }]`, and
the daemon picks the one that fits this printer. `core/conditions.py` matches a `when` over the device
facts (`adapter`, `fw_min`/`fw_max`, `arch`, `board_class`); an unknown dimension fails closed and no
matching variant drops the entry. New `variant_facts()` read verb feeds the pre-pass; capabilities
gain `arch` and `board_class` (the U1 reports `aarch64` and a memory-derived board class).

## 0.12.12-dev

The printer now has a stable identity, and a plugin's applied config is readable. Two additions for
the app's printer-scoped plugin config work (alpha.31):

- **Printer uuid.** At startup the daemon mints a uuid4 once and persists it at
  `etc/daemon/printer_uuid` under the data root (survives OTA, never regenerated while a value
  exists); `GET /status` now reports it as `printer_uuid` (null until a data root exists, so an old
  record or a dev run degrades honestly). Every computer can key its per-printer state to the same
  printer instead of its own app-local record id. New `core/printer_identity.py`.
- **`GET /plugins/{plugin_id}/config`** returns `{"vars": {...}}`, the user variables persisted next
  to the plugin at install/reconfigure time (empty for a var-less plugin, 404 for an unknown one).
  This is the app's tier-1 truth source for the installed Config tab, replacing its global-map
  re-derivation. Token-authed like every route.

Housekeeping: the env-overridable data root (`BESPOK3D_DATA_ROOT`) was declared in four places; it
is now the single `core/data_root.py` (`api/routes/paths.py` retired into it).

## 0.12.11-dev

Batch install and update were separated from the single-package path into their own modules: the batch
route moved to `api/routes/batch.py` and its orchestration to `core/packages/batch.py` +
`core/packages/installer_batch.py`, out of the packages route and the updater. A batch applies every
package first and defers the service restarts to a single restart at the end, the same restart-storm
protection a single install gets. This is the path the app's Collections "Install all" and "Update all"
ride, so a whole set of plugins lands with one Klipper/Moonraker bounce instead of one per plugin.

## 0.12.7-dev

Multiple patch fragments targeting the same file now apply CUMULATIVELY. The daemon's patch flow
fetched the stock file once as a pristine baseline, then applied EACH fragment independently against
that baseline and wrote it back, so a plugin shipping several fragments for one file (klipper-motion
patches `toolhead.py` four times, `resonance_tester.py` three) had every fragment past the first
applied to the unpatched original: a fragment whose context is an earlier fragment's addition failed
(only the single-fragment `shaper_calibrate.py` succeeded). The old in-place model patched the device
file directly, so fragments accumulated; the fetch-and-write-back rework lost that. Now
`core/packages/patches.py` groups fragments by target file and applies them in order to ONE working
copy of the baseline (`_patch_target`), so a later fragment builds on the earlier one, and writes the
cumulative result back once. Each fragment stays its own phase item, named for its diff, so a conflict
pins the exact fragment to re-author (the snap diff tool works at that granularity). The pristine
baseline is still kept once for restore, deduped across a file's fragments.

## 0.12.6-dev

A failed required install phase no longer passes as a clean install. Before, a patch whose hunks did
not apply logged the phase as failed but still returned the plugin as installed-and-working, with its
core effect silently missing. Now install settles its outcome by the phase log (`finalize_install_outcome`,
`core/packages/deactivation.py`): a clean run clears stale markers as before; a failed required phase
deactivates the half-applied plugin (drop its symlinks, restore any patched source, write
`deactivated.json`), the same protection recover gives a broken plugin, so the app shows it disabled,
not installed. The install log is retained for inspection (every phase is still returned and the plugin
dir stays on disk), and the install response `ok` now reflects the real phase outcome instead of a
hardcoded success. The restart safety net still owns a plugin it already deactivated; the marker check
leaves its diagnosis reason untouched.

## 0.12.1-dev

Daemon orchestrates, jinni actuates. The jinni is now a separate process the daemon parents
over a Unix socket, not an in-process class the daemon subclasses. Generic `core/` reaches it through
one seam (`core/jinni_client/`) plus the leaf contract shapes (`jinni.contracts`), enforced by
`scripts/generic_daemon_guard.py`; the retired `as_klipper_printer`, `ServiceActionVocabulary`, and the
`permissions()` snapshot are gone.

- **Print safety is blocked-action TOKENS.** The jinni owns the vocabulary (`RESTART_KLIPPER` /
  `RESTART_MOONRAKER` / `RESTART_DISPLAY`): `blocked_actions()` is the live set, `classify_commands()`
  tags each command. The print guard (`core/packages/print_guard.py`) is pure set membership and raises
  `BlockedActionError`, rendered as `409 {"error":"blocked","blocked_actions":[...]}`; the app localizes
  each token. `/ws/print-state` is a dumb relay over the streaming `subscribe-blocked-actions` verb.
- **Safety-net diagnosis is a token too.** `DeviceHealth.diagnosis` carries a machine token for a
  non-plugin cause (the U1's stock broker down, say); the daemon relays it, the app localizes it.
- **Separation-of-concerns splits.** The jinni is faceted one room per concern (layout / realization /
  facts / probing / health, plus protocol / service / printer_comms for the process and wire); the
  adapter's client and jinni were split by concern and the adapter gained its own gate.

DEVICE-VERIFIED on the U1 2026-06-16: the new daemon+jinni boundary drives plugin install and reinstall
on real hardware. That split is not fully realized yet. The daemon repo still ships the generic Klipper jinni
(`KlipperPrinterJinni` + the klipper facets + klippy/moonraker comms) and `core/safety` still names
Klipper/Moonraker; that is device knowledge, and the daemon's realm is the bespok3d filesystem only, so it
must move to a shared adapter-layer `klipper-jinni` library that device jinnis extend. Also remaining: the
mid-print blocked-action flip on a live print, the jinni RSS footprint measurement, and the escape
hatch (boot-gated inert mode plus declarative wiring-record replay), which is decided but not yet
built.

## 0.11.8-dev

First release cut from the standalone daemon repository, extracted from the Bespok3d monorepo
("b3 zero"). The daemon is now packaged as a publishable `.b3` and carries its own gate
(`scripts/check.sh`: ruff + mypy + pytest on Python 3.11), packer (`scripts/pack.sh`), and release CI.

No runtime behavior change versus the monorepo's `0.11.8-dev`. The only code change in the extraction
was making the daemon's strict mypy gate genuinely pass: 19 pre-existing type errors that the monorepo
gate had hidden (it ran mypy without the daemon's config) are now fixed, all type-only or runtime
no-ops (the full test suite is unchanged at 265 passed / 5 skipped).
