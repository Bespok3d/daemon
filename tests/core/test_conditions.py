"""The variant engine's pure matcher: which condition a set of device facts satisfies, and which
variant `select_variant` picks. No jinni, no IO; the facts are passed in directly."""
from core import conditions

_U1_FACTS = {
    "adapter": "snapmaker-u1",
    "firmware_version": "1.4.1",
    "arch": "aarch64",
    "board_class": "standard",
}


def test_empty_condition_matches_any_facts() -> None:
    assert conditions.matches({}, _U1_FACTS) is True
    assert conditions.matches({}, {}) is True


def test_adapter_condition_matches_only_its_adapter() -> None:
    assert conditions.matches({"adapter": "snapmaker-u1"}, _U1_FACTS) is True
    assert conditions.matches({"adapter": "prusa-mk4"}, _U1_FACTS) is False


def test_arch_condition_matches_only_its_arch() -> None:
    assert conditions.matches({"arch": "aarch64"}, _U1_FACTS) is True
    assert conditions.matches({"arch": "x86_64"}, _U1_FACTS) is False


def test_board_class_condition_matches_only_its_class() -> None:
    constrained = {**_U1_FACTS, "board_class": "constrained"}
    assert conditions.matches({"board_class": "constrained"}, constrained) is True
    assert conditions.matches({"board_class": "constrained"}, _U1_FACTS) is False


def test_kernel_release_condition_matches_only_the_running_kernel() -> None:
    junior = {**_U1_FACTS, "kernel_release": "6.1.99"}
    assert conditions.matches({"kernel_release": "6.1.99"}, junior) is True
    assert conditions.matches({"kernel_release": "6.1.75"}, junior) is False
    # A box whose jinni does not report a kernel (the generic "unknown") never matches a real .ko.
    assert conditions.matches({"kernel_release": "6.1.99"}, _U1_FACTS) is False


def test_vermagic_condition_matches_only_the_exact_version_magic() -> None:
    # The finer key: two kernels can share a release but differ in ABI-affecting config flags, so a
    # .ko variant can pin the exact version magic the kernel checks at insmod.
    junior = {**_U1_FACTS, "vermagic": "6.1.99 SMP preempt mod_unload aarch64"}
    assert conditions.matches({"vermagic": "6.1.99 SMP preempt mod_unload aarch64"}, junior) is True
    assert conditions.matches({"vermagic": "6.1.99 SMP preempt aarch64"}, junior) is False
    assert conditions.matches({"vermagic": "6.1.99 SMP preempt mod_unload aarch64"}, _U1_FACTS) is False  # noqa: E501


def test_ko_variant_selected_by_vermagic_over_a_release_fallback() -> None:
    variants: list[dict] = [
        {"when": {"vermagic": "6.1.99 SMP preempt mod_unload aarch64"}, "src": "files/tun-exact.ko"},  # noqa: E501
        {"when": {"kernel_release": "6.1.99"}, "src": "files/tun-release.ko"},
    ]
    exact = {**_U1_FACTS, "kernel_release": "6.1.99",
             "vermagic": "6.1.99 SMP preempt mod_unload aarch64"}
    exact_variant = conditions.select_variant(variants, exact)
    assert exact_variant is not None and exact_variant["src"] == "files/tun-exact.ko"
    # a kernel that shares the release but not the exact magic falls through to the release variant
    release_only = {**_U1_FACTS, "kernel_release": "6.1.99", "vermagic": "6.1.99 SMP aarch64"}
    release_variant = conditions.select_variant(variants, release_only)
    assert release_variant is not None and release_variant["src"] == "files/tun-release.ko"


def test_ko_variant_is_skipped_when_no_kernel_matches() -> None:
    tun_place = {
        "class": "kernel-module", "name": "tun.ko",
        "variants": [{"when": {"kernel_release": "6.1.99"}, "src": "files/modules/tun-6.1.99.ko"}],
    }
    junior = {"kernel_release": "6.1.99"}
    other = {"kernel_release": "5.10.0"}
    assert conditions.resolve_variants({"place": [tun_place]}, junior)["place"][0][
        "src"
    ] == "files/modules/tun-6.1.99.ko"
    assert conditions.resolve_variants({"place": [tun_place]}, other)["place"] == []


def test_every_named_dimension_must_hold() -> None:
    both = {"adapter": "snapmaker-u1", "arch": "aarch64"}
    assert conditions.matches(both, _U1_FACTS) is True
    assert conditions.matches({**both, "arch": "x86_64"}, _U1_FACTS) is False


def test_fw_min_is_an_inclusive_floor() -> None:
    assert conditions.matches({"fw_min": "1.4.1"}, _U1_FACTS) is True
    assert conditions.matches({"fw_min": "1.4.0"}, _U1_FACTS) is True
    assert conditions.matches({"fw_min": "1.5.0"}, _U1_FACTS) is False


def test_fw_max_is_an_inclusive_ceiling() -> None:
    assert conditions.matches({"fw_max": "1.4.1"}, _U1_FACTS) is True
    assert conditions.matches({"fw_max": "1.4.0.244"}, _U1_FACTS) is False
    assert conditions.matches({"fw_max": "1.5.0"}, _U1_FACTS) is True


def test_fw_range_compares_uneven_length_versions_by_zero_padding() -> None:
    # 1.4 and 1.4.0 are the same version; a shorter bound must not read as lower.
    facts = {**_U1_FACTS, "firmware_version": "1.4"}
    assert conditions.matches({"fw_min": "1.4.0", "fw_max": "1.4.0"}, facts) is True


def test_fw_bound_never_matches_an_unknown_or_nonnumeric_version() -> None:
    unknown = {**_U1_FACTS, "firmware_version": "unknown"}
    assert conditions.matches({"fw_min": "1.0.0"}, unknown) is False
    assert conditions.matches({"fw_max": "9.9.9"}, unknown) is False


def test_an_unknown_dimension_fails_closed() -> None:
    # A future dimension (a kernel vermagic, packet 3) an older engine does not know must never
    # let a variant authored for it match; it is skipped, not mis-selected.
    assert conditions.matches({"vermagic": "6.1.99"}, _U1_FACTS) is False


def test_select_variant_returns_the_first_matching_in_order() -> None:
    variants: list[dict] = [
        {"when": {"arch": "x86_64"}, "src": "files/wrong.ko"},
        {"when": {"arch": "aarch64"}, "src": "files/tun-aarch64.ko"},
        {"when": {"arch": "aarch64"}, "src": "files/tun-second.ko"},
    ]
    selected = conditions.select_variant(variants, _U1_FACTS)
    assert selected is not None
    assert selected["src"] == "files/tun-aarch64.ko"


def test_select_variant_falls_back_to_a_conditionless_variant() -> None:
    variants: list[dict] = [
        {"when": {"board_class": "constrained"}, "src": "files/light.bin"},
        {"src": "files/default.bin"},
    ]
    selected = conditions.select_variant(variants, _U1_FACTS)
    assert selected is not None
    assert selected["src"] == "files/default.bin"


def test_a_null_when_is_the_catch_all_not_a_crash() -> None:
    # An author writing the catch-all explicitly as `when: null` must not crash the matcher.
    variants: list[dict] = [{"when": None, "src": "files/default.bin"}]
    selected = conditions.select_variant(variants, _U1_FACTS)
    assert selected is not None
    assert selected["src"] == "files/default.bin"


def test_a_numeric_firmware_bound_compares_rather_than_crashing() -> None:
    # A bound written unquoted (`fw_min: 1.4`) arrives as a JSON number, not a string.
    assert conditions.matches({"fw_min": 1.4}, _U1_FACTS) is True
    assert conditions.matches({"fw_min": 1.5}, _U1_FACTS) is False


def test_select_variant_is_none_when_nothing_matches() -> None:
    variants: list[dict] = [{"when": {"arch": "x86_64"}, "src": "files/wrong.ko"}]
    assert conditions.select_variant(variants, _U1_FACTS) is None
