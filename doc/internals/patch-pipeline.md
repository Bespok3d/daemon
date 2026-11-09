<!-- SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# The patch pipeline

A plugin that has to change a file the printer already owns (a Klipper extra, a Moonraker config, a
vendored web bundle) declares `install.instrument` entries in its manifest, each naming a target file
and a unified diff. This document is how the daemon turns those into a changed file on the printer,
and how it gets the printer back to stock afterwards. The code is `core/packages/baseline.py`,
`core/packages/patches.py` and `core/packages/patch_handover.py`.

## Who may patch Snapmaker's own files: the base layer, and nothing else (ADR-0043)

Every file the printer maker ships has exactly one owning package, and those packages are that device
family's base layer. For the Snapmaker U1 it is `u1-base`: six patch-only plugins, one per stock file
owned, plus a Collection that installs all six. A feature plugin ships no diff against a stock file at
all. It names the door it needs with a `require` entry against the service its owning base member
provides, and calls that door from its own Klipper module at run time.

**This is a publishing rule, enforced where plugins get published. It is not a printer check.** The
daemon does not refuse a `klipper-source` instrument entry from any package, and nothing on the
printer tests membership of a base plugin list (owner, 2026-08-22).

Single ownership is what makes the baseline machinery correct: `derive_stock` recovers stock text by
reverse-applying one plugin's own fragments, so a second owner of the same file would capture already
patched text as its baseline and write that back on uninstall.

## The one rule

**The diffs are always applied to the stock original, never to whatever is on the printer right now.**
Everything below exists to make that true even after a re-provision, a failed recovery, or a second
plugin having patched the same file first.

## Where a stock original is kept

Each plugin holds its own copies under `patches_orig/` inside its own plugin directory
(`STOCK_COPIES_DIR` in `baseline.py`). One kept copy per target file.

**The copy is keyed by the target's full path, not by its file name.** The target's own path is made
relative and mirrored inside `patches_orig/`, so `/home/lava/moonraker/moonraker.conf` and
`/home/lava/klipper/moonraker.conf` are two separate copies. Keyed by bare name they would have been
one, and an uninstall would then have written the wrong file back over one of the two.

A printer patched by a daemon older than 0.13.0 keeps its copies under the bare name. That copy is the
only record of what the file looked like stock, so `kept_original()` uses a bare-name copy wherever
one is still on disk and falls back to the mirrored path otherwise. Updating the daemon never orphans
the copy a printer needs to get back to stock, and nothing migrates or rewrites the old copies.

## Establishing the baseline

`baseline.establish(target, baseline_path, fragments)` runs before any fragment touches anything:

1. **Capture, only if nothing is held yet.** The device file is read through the jinni
   (`jinni_client.fetch`); reading a device file is the jinni's job, not the daemon's (ADR-0037). A
   target that does not exist on the printer is reported as a failure and nothing is written.
2. **Self-heal to stock.** `derive_stock()` checks whether the held baseline is already the patched
   output of these same diffs, and if it is, reverses them back off it and rewrites the baseline in
   place. A file the diffs still apply cleanly to is left alone (it is stock, or close enough). A file
   that is neither is also left alone, so the normal apply reports its own reject and a plugin author
   sees why their patch did not fit instead of a silent pre-emption.

Without step 2, a re-provision that captures an already-patched file traps the plugin re-patching its
own output: the apply fails on every retry and the plugin silently stops working.

## Applying

`patches.apply_patches()` works per target file, not per fragment:

- All of that target's fragments are applied cumulatively to a `.b3work` scratch copy taken from the
  kept original.
- The device file is written back **once, and only if every fragment applied cleanly.** A partial
  apply never reaches the printer.

## Restoring

`patches.restore_original_files()` writes each kept original back over its target. Targets are
deduplicated, so a file patched by several fragments is restored once, and an empty kept copy is
skipped rather than truncating the printer's file to nothing.

After a firmware update a kept original is the old firmware's file wherever the update replaced
the printer's file, and writing it back would put old firmware code on a printer that runs the new
one. So before a plugin is switched off (on request, by the safety net, all at once, or by recovery
because a service it needs did not come back or a setting it requires is missing) and before it is
removed, `settle_originals.settle_kept_originals()` makes each kept original the original of the
printer's file as it is now: the file with this plugin's patches reversed off it
(`baseline.without_patches()`). That puts the new firmware's lines back and keeps a user's own edit
and another plugin's patches. When the patches cannot be reversed off the file (the update replaced
it and the change is gone), the copy is dropped together with its undo step in the wiring record,
and the file is left as the new firmware made it. A copy an older daemon kept under the bare file
name, when the plugin patches two files of that name, cannot say which one it came from and is left
as it is. A failed install or update never settles: its kept copies are the true originals and must
go back.

A switch-off cannot be refused, so a check that fails there (the printer does not answer, the
settings file is torn, a missing setting names the patched file) drops the plugin's copies, leaves
the file as it is and says so in the reason (`settle_before_switch_off()`), or in the daemon's log
when every plugin is switched off at once; a removal raises instead.

A plugin switched off before the update already put its originals back but still keeps them, so
removing it later would write them again. At the start of every recovery,
`recovery/stale_originals.settle_kept_originals_of_switched_off()` settles them the same way. A
plugin whose manifest cannot be read names no patches, so none of its copies can be checked:
recovery drops them all (`drop_kept_originals()`), and a reinstall captures the file afresh. A check
that fails drops the plugin's copies the same way, the row's reason says so, and the rest of the
printer is recovered.

Recovery also puts back on the plugins the safety net switched off, and the plugins switched off
along with them (`recovery/put_back.py`): a firmware update wipes files plugins link into the
printer, so the net can switch a working plugin off before recovery links them again. The safety
net judges them again afterwards. A plugin a person switched off stays off, and so do the plugins
switched off with it (`stranded_on_request_reason()`). A plugin the net switches off during a
recovery has failed with everything linked again, so its reason (`safety_net_reason()`) keeps the
next recovery from putting it back.

A plugin whose `manifest.json` cannot be read has nothing left to say which files it patched. The
kept copies say it themselves: each is filed under the full path of the file it was taken from, so
where it sits names its target. `lost_manifest_restore.restore_originals_without_manifest()` reads
the targets back out and restores through the same write, and uninstall takes that route whenever
the manifest is unreadable, because the removal is the last moment those copies exist. Recovery
has already dropped the copies of a plugin it found torn, so this route only acts for a manifest torn
since the last recovery. A copy filed by an older daemon under the bare file name carries no path,
so it is left alone rather than written over a guessed one.

## Handover: one file, one owner

More than one installed plugin can patch the same target today, and each keeps its own copy of that
file's original in its own `patches_orig/`. `patch_handover.adopt_patch_ownership()` collapses that to
a single owner:

- It reads the installed manifests to find every plugin that patches the target, and takes each
  one's patches back off the live file (`live_original.original_of_the_live_file()`). A kept copy is
  never adopted as it is: after a firmware update it is the old firmware's file, and adopting it put
  a firmware 2.0 file back on a printer running 2.1.
- The result counts only when every owner's patches are proven off it: they came off it, they fit
  it again, or the owner cannot have them on the file. A switched-off owner took them off when it was switched off.
  In a recovery, patches that neither fit the file nor come off it were written for the firmware the
  printer ran before. Otherwise it refuses with `NO_STOCK_ORIGINAL` rather than baking another
  plugin's changes in as the baseline.
- The old owners' copies of that file are dropped once the new owner holds it, so a later restore can
  only ever write back one original.
- It is **idempotent by state and carries no marker file**: a plugin that already holds the file is
  already its owner, so a second run finds nothing to adopt and changes nothing.

## Who owns what, settled on every install

Ownership is settled as two phases of the ordinary install, run in this order and before the first
fragment is applied. They run for every plugin on every install and every update, never as a one-off
migration step, so a printer that has a file to hand over and a printer that never had one both end
in the same place. `installer.apply_install_deferred()` runs them, and install and update share it.

1. **`relinquish`** (`patch_relinquish.relinquish_phase()`): every file this plugin holds a stock copy
   of and no longer patches is written back to stock, and only then is the copy released. A plugin
   hands a file over by shipping a version that no longer patches it, and its kept copy is the only
   record of what that file looked like before, so the file has to go back while the copy is still
   held. Left to a later run there would be nothing to put back from. The copies themselves say which
   files the plugin used to patch, so the old manifest does not have to still be on the printer. A
   copy an older daemon filed under the bare file name names no path and is left alone.
2. **`adopt`** (`patch_handover.adoption_phase()`): the plugin takes on the true original of every
   file it does patch, one call of `adopt_patch_ownership()` per target file.

A failed `relinquish` stops the install before `adopt` runs, so a file that could not be put back is
never then adopted from its own patched text. Either phase failing stops the install before
`patches`, and the caller settles the half-run install the way it settles any failed phase, by taking
the plugin back off the printer. `NO_STOCK_ORIGINAL` therefore costs a printer the install, never its
working state.
