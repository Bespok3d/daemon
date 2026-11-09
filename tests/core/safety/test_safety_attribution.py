# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pure attribution tests: a jinni failure SIGNAL in, culprit plugin out.

The jinni read the failing identifier out of the device log; the daemon only maps it to the plugin
that placed it, via its own placement index. No log parsing here, that lives with the jinni.
"""
from pathlib import Path

from core.safety.attribution import AttributionIndex, Placement, attribute, build_index
from protocol import FailureSignals


def test_attribute_by_config_section() -> None:
    index = AttributionIndex(
        by_path={}, by_module={}, by_section={"temperature_sensor Rockchip": "cpu-temp"},
    )
    culprit, signal = attribute(FailureSignals(sections=("temperature_sensor Rockchip",)), index)
    assert culprit == "cpu-temp"
    assert "temperature_sensor Rockchip" in signal


def test_attribute_by_import_module() -> None:
    index = AttributionIndex(by_path={}, by_module={"humanize": "status-feed"}, by_section={})
    culprit, _signal = attribute(FailureSignals(modules=("humanize",)), index)
    assert culprit == "status-feed"


def test_attribute_by_traceback_file() -> None:
    extra = "/home/lava/klipper/klippy/extras/print_time_human.py"
    index = AttributionIndex(by_path={extra: "print-time-human"}, by_module={}, by_section={})
    culprit, _signal = attribute(FailureSignals(files=(extra,)), index)
    assert culprit == "print-time-human"


def test_attribute_returns_none_when_no_signal_matches() -> None:
    index = AttributionIndex(by_path={}, by_module={}, by_section={})
    culprit, signal = attribute(FailureSignals(sections=("unknown",)), index)
    assert culprit is None
    assert signal == ""


def test_build_index_maps_modules_and_sections(tmp_path: Path) -> None:
    cfg = tmp_path / "notifier.cfg"
    cfg.write_text("[notifier phone]\nurl: x\n")
    index = build_index([
        Placement("moonraker-notify", destinations=[str(cfg)], module_names=[]),
        Placement("print-time-human", destinations=[], module_names=["humanize"]),
    ])
    assert index.by_section["notifier phone"] == "moonraker-notify"
    assert index.by_module["humanize"] == "print-time-human"


def test_a_section_klipper_reports_in_lowercase_is_attributed(tmp_path: Path) -> None:
    # Junior: a plugin placed [AFC]; Klipper halted with "Section 'afc' is not a valid config
    # section", and a case-sensitive match left the plugin on and the printer stopped.
    afc_config = tmp_path / "AFC.cfg"
    afc_config.write_text("[AFC]\nVarFile: ../../AFC.var\n")
    index = build_index([Placement("afc-lite", destinations=[str(afc_config)], module_names=[])])
    culprit, signal = attribute(FailureSignals(sections=("afc",)), index)
    assert culprit == "afc-lite"
    assert "[AFC]" in signal


def test_a_section_matching_in_exact_case_beats_one_in_another_case(tmp_path: Path) -> None:
    capital_config = tmp_path / "capital.cfg"
    capital_config.write_text("[Toolhead]\n")
    small_config = tmp_path / "small.cfg"
    small_config.write_text("[toolhead]\n")
    index = build_index([
        Placement("capital-plugin", destinations=[str(capital_config)], module_names=[]),
        Placement("small-plugin", destinations=[str(small_config)], module_names=[]),
    ])
    culprit, _ = attribute(FailureSignals(sections=("toolhead",)), index)
    assert culprit == "small-plugin"
