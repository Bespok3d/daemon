<!-- SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# The patch pipeline

A plugin that has to change a file the printer already owns (a Klipper extra, a Moonraker config, a
vendored web bundle) declares `install.instrument` entries in its manifest, each naming a target file
and a unified diff. This document is how the daemon turns those into a changed file on the printer,
and how it gets the printer back to stock afterwards. The code is `core/packages/baseline.py`,
`core/packages/patches.py` and `core/packages/patch_handover.py`.

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

## Handover: one file, one owner

More than one installed plugin can patch the same target today, and each keeps its own copy of that
file's original in its own `patches_orig/`. `patch_handover.adopt_patch_ownership()` collapses that to
a single owner:

- It reads the installed manifests to find every plugin that patches the target, and adopts the one
  kept copy that no known patch has been applied to.
- When no kept copy qualifies, it reverses the known patches back off the live file to recover the
  original. If neither works it refuses with `NO_STOCK_ORIGINAL` rather than baking another plugin's
  changes in as the baseline.
- The old owners' copies of that file are dropped once the new owner holds it, so a later restore can
  only ever write back one original.
- It is **idempotent by state and carries no marker file**: a plugin that already holds the file is
  already its owner, so a second run finds nothing to adopt and changes nothing.

**As of daemon 0.13.0 this function has no production caller.** It is the mechanism the base layer will
use when it takes patching over from the plugins that do it today, so that an already-patched printer
ends up on the base layer's text whatever order the updates arrive in. Until that ADR lands and the
caller exists, adoption never runs on a printer.

## Known leftover (open, not fixed in 0.13.0)

A plugin whose `manifest.json` is lost or unreadable is invisible to the pipeline: it keeps its patched
file on the printer forever, and its kept original is deleted along with the plugin folder, so nothing
can put the file back to stock. Tracked in `~/.claude/plans/base-layer-owns-patching/daemon-leftovers.seed.md`.
