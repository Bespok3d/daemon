# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Refusal cases the variant engine must hold: no variant matches, and a malformed condition.

A manifest's `variants` block is community authored JSON. `core/intent.py` hands it to
`resolve_variants` with no schema check first, so a wrong-typed `when` (a manifest author's typo,
`when: "aarch64"` where a dict was meant) reaches conditions.py unfiltered. This file proves the
engine's behaviour on the documented no-match path, then on that undocumented malformed one."""
from core import conditions

_U1_FACTS = {
    "adapter": "snapmaker-u1",
    "firmware_version": "1.4.1",
    "arch": "aarch64",
    "board_class": "standard",
}


def test_resolve_variants_drops_only_the_entry_with_no_matching_variant() -> None:
    """A section with several variant-carrying entries drops the ones that match nothing while
    keeping the ones that do, not the whole section (existing coverage only exercises a single-entry
    section)."""
    matching_module = {
        "class": "kernel-module", "name": "tun.ko",
        "variants": [{"when": {"arch": "aarch64"}, "src": "files/tun-aarch64.ko"}],
    }
    unmatched_module = {
        "class": "kernel-module", "name": "spi.ko",
        "variants": [{"when": {"arch": "x86_64"}, "src": "files/spi-x86_64.ko"}],
    }
    place_ops = {"place": [matching_module, unmatched_module]}
    resolved = conditions.resolve_variants(place_ops, _U1_FACTS)
    remaining_names = [entry["name"] for entry in resolved["place"]]
    assert remaining_names == ["tun.ko"]


def test_malformed_when_refuses_instead_of_crashing_the_install_path() -> None:
    """A `when` that is not a dict of dimensions must be refused like any other non-matching
    condition, never raise out of the install pre-pass and abort resolution of every other entry."""
    malformed_condition = "aarch64"
    assert conditions.matches(malformed_condition, _U1_FACTS) is False


def test_select_variant_skips_a_malformed_when_and_still_reaches_the_catch_all() -> None:
    """The real shape this bites in: one variant in the list has a malformed `when`, a later one
    is the well-formed catch-all. The malformed entry must be skipped, not abort the whole
    selection."""
    variants: list[dict] = [
        {"when": "aarch64", "src": "files/malformed.ko"},
        {"src": "files/default.ko"},
    ]
    selected = conditions.select_variant(variants, _U1_FACTS)
    assert selected is not None
    assert selected["src"] == "files/default.ko"
