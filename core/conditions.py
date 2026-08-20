# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The variant engine: pick which of a manifest entry's variants applies to THIS printer.

A manifest place/instrument entry may carry a `variants` list of `{ when, src|diff }`. `when` is a
condition over the device facts the daemon holds (adapter, firmware range, arch, board class).
`matches` decides one condition, `select_variant` returns the first variant a set of facts fits, and
`resolve_variants` folds the selected variant into each install entry (dropping an entry no variant
matches). It names no device fact of its own and does no IO, so it is unit tested without a jinni;
`intent.py` runs the pre-pass, and the package layer supplies the facts from
`jinni_client.variant_facts()`.

The dimension set is small and closed on purpose. `kernel_release` (a `.ko` built per running
kernel) is one exact dimension; `vermagic` is the finer one for a module whose ABI differs between
two kernels that share a release. An unknown dimension fails closed, so a manifest authored for a
dimension an older daemon does not know is skipped, never mis-selected.
"""

from .versions import version_at_least, version_at_most

# The install sections whose entries may carry `variants`: a payload file (`place`) or a carried
# diff (`instrument`) that differs per printer (a kernel module built per kernel, a binary per
# arch). Services and restart hooks are device-uniform, so they take no variants.
_VARIANT_SECTIONS = ("place", "instrument")

# The dimensions matched by exact string equality against the same-named fact. `kernel_release` is
# the running kernel's `uname -r`, which a cross-built `.ko` variant must match; `vermagic` is the
# exact version-magic string the kernel checks at insmod (release plus ABI-affecting config flags),
# the finer key for a `.ko`. Range dimensions (fw_min / fw_max) are handled apart, since they
# compare a version rather than test equality.
_EXACT_DIMENSIONS = frozenset({"adapter", "arch", "board_class", "kernel_release", "vermagic"})


def matches(condition: object, facts: dict[str, str]) -> bool:
    """True when every dimension the condition names is satisfied by the facts. An empty condition
    matches anything (the catch-all fallback variant); an unknown dimension fails closed, and so
    does a `when` that is not a set of dimensions at all: nothing validates a manifest before this
    runs, so one mistyped entry must cost that entry and never the whole printer's variant pass."""
    if not isinstance(condition, dict):
        return False
    return all(_dimension_holds(dimension, value, facts) for dimension, value in condition.items())


def select_variant(variants: list[dict], facts: dict[str, str]) -> dict | None:
    """The first variant whose `when` the facts satisfy (ordered, first match wins), or None when
    none apply so the caller skips the entry. A missing or null `when` is the catch-all fallback."""
    matching = (variant for variant in variants if matches(variant.get("when") or {}, facts))
    return next(matching, None)


def resolve_variants(install: dict, facts: dict[str, str]) -> dict:
    """Pre-pass: replace each variant-carrying place/instrument entry with the one that applies to
    this printer, dropping an entry no variant matches. Every other section is left untouched."""
    resolved = dict(install)
    for section in _VARIANT_SECTIONS:
        if section in install:
            resolved[section] = _resolve_section(install[section], facts)
    return resolved


def _resolve_section(entries: list[dict], facts: dict[str, str]) -> list[dict]:
    resolved = [_resolve_entry(entry, facts) for entry in entries]
    return [entry for entry in resolved if entry is not None]


def _resolve_entry(entry: dict, facts: dict[str, str]) -> dict | None:
    """Fold an entry's matching variant into it, or None to skip the entry when nothing matches. An
    entry with no `variants` passes through unchanged; a variant's fields (its `src`/`diff`, any
    `name` override) win over the base entry's."""
    variants = entry.get("variants")
    if variants is None:
        return entry
    selected = select_variant(variants, facts)
    if selected is None:
        return None
    base = {key: value for key, value in entry.items() if key != "variants"}
    chosen = {key: value for key, value in selected.items() if key != "when"}
    return {**base, **chosen}


def _dimension_holds(dimension: str, value: str, facts: dict[str, str]) -> bool:
    if dimension in _EXACT_DIMENSIONS:
        return facts.get(dimension) == value
    if dimension == "fw_min":
        return version_at_least(facts.get("firmware_version", ""), value)
    if dimension == "fw_max":
        return version_at_most(facts.get("firmware_version", ""), value)
    return False
