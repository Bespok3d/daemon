"""Pure attribution tests: failure signal in, culprit plugin out. No plugin enumeration, no I/O."""
from pathlib import Path

from core.safety.attribution import AttributionIndex, Placement, attribute_failure, build_index


def test_attribute_failure_by_config_section() -> None:
    index = AttributionIndex(
        by_path={}, by_module={}, by_section={"temperature_sensor Rockchip": "cpu-temp"},
    )
    culprit, signal = attribute_failure(
        "Section 'temperature_sensor Rockchip' is not a valid config section", index,
    )
    assert culprit == "cpu-temp"
    assert "temperature_sensor Rockchip" in signal


def test_attribute_failure_by_import_module() -> None:
    index = AttributionIndex(by_path={}, by_module={"humanize": "status-feed"}, by_section={})
    culprit, _signal = attribute_failure("ModuleNotFoundError: No module named 'humanize'", index)
    assert culprit == "status-feed"


def test_attribute_failure_by_traceback_path() -> None:
    extra = "/home/lava/klipper/klippy/extras/print_time_human.py"
    index = AttributionIndex(by_path={extra: "print-time-human"}, by_module={}, by_section={})
    log = f'Traceback (most recent call last):\n  File "{extra}", line 3\n    boom\nNameError'
    culprit, _signal = attribute_failure(log, index)
    assert culprit == "print-time-human"


def test_attribute_failure_returns_none_when_unrecognized() -> None:
    index = AttributionIndex(by_path={}, by_module={}, by_section={})
    culprit, signal = attribute_failure("something went wrong but nothing matches", index)
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
