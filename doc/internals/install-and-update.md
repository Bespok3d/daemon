<!-- SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Install and update: what the printer will and will not accept

An install puts a plugin on the printer that was not there. An update replaces one that was. They
differ in what they do to a plugin already on the printer, **never in what the printer is willing to
hold**. This document is the checks, in the order they run, and what a refusal leaves behind.

## An update runs the install checks

`core/packages/updater.py` and `core/packages/installer_batch.py` are the same three steps:

    plan_batch(...)  ->  settle_refusals(...)  ->  run_batch(..., OperationKind.UPDATE | INSTALL)

`settle_refusals()` (`core/packages/batch_refusals.py`) is the shared step. There is no update path
that skips it and no relaxed variant of it. An update that would leave the printer holding a
combination it would have refused at install time is refused.

Guarded by `tests/core/packages/test_packages_update_refusals.py`:

| Test | What it holds |
| --- | --- |
| `test_an_update_needing_an_absent_service_is_refused_with_nothing_written` | a new version that starts requiring a service nothing provides does not land |
| `test_an_update_excluding_an_installed_plugin_is_refused_with_nothing_written` | a new version that starts conflicting with an installed plugin does not land |
| `test_a_sibling_in_the_same_update_supplies_the_service` | a requirement met by another package in the same batch counts as met |

## The version floors

Two floors, no ceilings. A pair is refused only when it is provably bad; a version that cannot be
read is never a refusal.

| Floor | Declared in | Enforced by | Meaning |
| --- | --- | --- | --- |
| Package needs this daemon | `min_daemon_version` in the package manifest | `guard_daemon_reaches_the_package_floor()` in `core/packages/pair_guard.py`, called from `unpack_package()` before a byte is extracted | the printer refuses a package written for a newer daemon than it runs |
| Daemon needs this jinni | `MIN_JINNI_VERSION` in `version.py`, served on `/capabilities` as `min_jinni_version` | `guard_compatible_pair()` in `core/packages/pair_guard.py` | the daemon will not drive an adapter jinni older than it was built against |

The refusal carries WHICH SIDE is behind and both version numbers as machine values
(`IncompatiblePairError`). The daemon never writes the sentence a user reads; the client localizes it
(ADR-0037). Tests: `tests/core/test_daemon_floor_guard.py`, `tests/core/test_pair_guard.py`.

`core/packages/daemon_services.py` is the same idea for a capability rather than a number. A name in
`DAEMON_SERVICES` is a service the daemon build supplies itself, so a package can `require` it and an
older daemon refuses that package for an unmet requirement instead of installing something it cannot
honour. A name is added by the release that starts honouring the capability and is never removed.
Today the set holds one name, `migrate-patch`.

## Every refusal

| Refused when | Error | Where | Runs |
| --- | --- | --- | --- |
| A print is running or paused and the op needs a blocked action | `BlockedActionError` | `print_guard.py` | before extraction |
| The package asks for a newer daemon than this printer runs | `IncompatiblePairError` (daemon side) | `pair_guard.py` | before extraction |
| The jinni is older than this daemon will drive | `IncompatiblePairError` (jinni side) | `pair_guard.py` | before the op |
| The package does not fit the printer's free space | `ValueError` | `unpacked_size.py` | before extraction |
| The zip carries a member the manifest does not declare, or one whose path escapes the plugin directory | `IntegrityError` | `archive.py` | during extraction |
| A member unpacks to more than it declared, or the write fails part way through | `ValueError` | `extraction.py` | during extraction |
| A placed file's sha256 does not match the manifest | `IntegrityError` (`CHECKSUM_MISMATCH`) | `file_drift.py` | after extraction |
| The package's Python dependencies were never baked into it | `ValueError` | `baked_deps.py` | after extraction |
| The package conflicts with an installed plugin | `ConflictError` | `batch_refusals.py` (batch), `install_refusals.py` (single) | batch: before extraction |
| A service the package requires is provided by nothing installed and by no sibling in the batch | `RequirementError` | `batch_refusals.py`, `install_refusals.py` | batch: before extraction |
| A setting the manifest marks required arrived with no value and has no default | `MissingSettingError` | `user_vars.py` | after extraction |
| A person asks to uninstall or deactivate a plugin other installed plugins depend on | `DependentsError` | `uninstaller.py`, `deactivator.py`, `batch_uninstaller.py` | on request |

The size check is **free space on the printer's own disk minus a 32 MB reserve**
(`FREE_SPACE_RESERVE_BYTES`), measured against the sizes the zip declares for its members. It is not a
fixed number of megabytes, so the same package can fit one printer and be refused by another.

**`DependentsError` is a refusal only when a person asked.** The self-heal path calls
`deactivate_with_dependents()` (`core/packages/deactivator.py`), which cascades loudly through the
dependents instead of refusing, because a printer that has already broken must end up usable rather
than blocked on a dependency graph.

## What a refused update does not touch

**A refusal decided before the package is opened touches nothing at all.** The installed plugin, its
placed files, the settings the user typed and its kept stock originals under `patches_orig/` are
exactly as they were. That is every batch-level refusal (conflict, unmet requirement), both version
floors, the print guard and the size check, and it is what the three update tests above assert.

**A refusal decided after extraction takes the extraction back off the printer**
(`discard_extraction()`, which removes the whole plugin directory). Otherwise `/capabilities` would
report a plugin the daemon never applied. The one refusal that deliberately does not do this is the
unbaked-dependencies one when it is replacing an existing install: that directory is also where the
older version's stock originals and settings live, so it is kept.

**A write that fails part way through is taken back the same way** (`extract_or_discard()` in
`core/packages/extraction.py`). The size check reads the sizes the zip DECLARES, so a member whose
compressed stream really holds far more than that passes every check and only fails once it is being
written; a full disk does the same whatever the package declared. A first install has its part written
tree removed; a version replacing one already installed keeps the directory, for the same reason the
unbaked-dependencies refusal does.

## Known leftovers (open, not fixed in 0.13.0)

- A plugin that loses its `manifest.json` keeps its patched file on the printer forever, and its kept
  stock original is deleted with the plugin folder.
- One torn manifest stops the whole OTA recovery pass instead of that plugin being skipped and the
  rest recovered.

Both are seeded at `~/.claude/plans/base-layer-owns-patching/daemon-leftovers.seed.md`.
