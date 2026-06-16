# Changelog

## 0.12.7-dev

Multiple patch fragments targeting the same file now apply CUMULATIVELY. The ADR-0037 patch flow
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

ADR-0037 (daemon orchestrates, jinni actuates). The jinni is now a separate process the daemon parents
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
on real hardware. ADR-0037 is NOT done yet. The daemon repo still ships the generic Klipper jinni
(`KlipperPrinterJinni` + the klipper facets + klippy/moonraker comms) and `core/safety` still names
Klipper/Moonraker; that is device knowledge, and the daemon's realm is the bespok3d filesystem only, so it
must move to a shared adapter-layer `klipper-jinni` library that device jinnis extend. Also remaining: the
mid-print blocked-action flip on a live print, the jinni RSS footprint measurement, and the decision-6
escape hatch (boot-gated inert mode plus declarative wiring-record replay), which is decided but not yet
built.

## 0.11.8-dev

First release cut from the standalone daemon repository, extracted from the Bespok3d monorepo
(ADR-0030, "b3 zero"). The daemon is now packaged as a publishable `.b3` and carries its own gate
(`scripts/check.sh`: ruff + mypy + pytest on Python 3.11), packer (`scripts/pack.sh`), and release CI.

No runtime behavior change versus the monorepo's `0.11.8-dev`. The only code change in the extraction
was making the daemon's strict mypy gate genuinely pass: 19 pre-existing type errors that the monorepo
gate had hidden (it ran mypy without the daemon's config) are now fixed, all type-only or runtime
no-ops (the full test suite is unchanged at 265 passed / 5 skipped).
