"""Pure decision tests for the safety net: build evidence as data, assert the verdict and culprit.

No I/O, no monkeypatching - this is the brain, exercised with values. `escaped` (reached the
catch-all) is asserted true ONLY for a genuinely unattributable failure, so a regression that lets a
known failure slip past its specific fixer fails here.
"""
from core.packages.recovery import restart
from core.safety import (
    AttributionIndex,
    FailureEvidence,
    OperationContext,
    OperationKind,
    decide,
    is_healthy,
)
from core.safety.decision import Decision
from core.safety.health import MoonrakerInfo


def _evidence(*, klipper_reachable: bool = True,  # noqa: PLR0913
              failed_components: list[str] | None = None,
              warnings: list[str] | None = None, klipper_log: str = "", moonraker_log: str = "",
              mqtt_up: bool = True, index: AttributionIndex | None = None) -> FailureEvidence:
    return FailureEvidence(
        klipper_reachable=klipper_reachable,
        klipper_log=klipper_log,
        moonraker=MoonrakerInfo(reachable=True, raw="", failed_components=failed_components or [],
                                warnings=warnings or []),
        moonraker_log=moonraker_log,
        mqtt_up=mqtt_up,
        index=index or AttributionIndex(by_path={}, by_module={}, by_section={}),
    )


def _ctx(plugin_id: str | None = "moonraker-notify",
         kind: OperationKind = OperationKind.INSTALL) -> OperationContext:
    return OperationContext(kind, plugin_id=plugin_id)


def test_is_healthy_requires_reachable_and_no_failed_components() -> None:
    assert is_healthy(_evidence()) is True
    assert is_healthy(_evidence(failed_components=["notifier"])) is False
    assert is_healthy(_evidence(klipper_reachable=False)) is False


def test_decide_blames_failed_moonraker_component() -> None:
    # The bug that started all this: Moonraker reachable but notifier failed to import apprise.
    index = AttributionIndex(by_path={}, by_module={}, by_section={"notifier phone": "moonraker-notify"})  # noqa: E501
    decision = decide(_evidence(failed_components=["notifier"], index=index), _ctx())
    assert decision.culprit == "moonraker-notify"
    assert decision.fixer == "moonraker-component"
    assert decision.escaped is False


def test_recovery_result_reports_first_failure_traceback_not_clean_log() -> None:
    """The reported log must be the FIRST-failure traceback, not a re-read of the live log after the
    recovery restart succeeded (which is clean). Health is still judged on the final evidence."""
    traceback = 'File "/home/lava/klipper/klippy/extras/foo.py"\nModuleNotFoundError: apprise'
    failure = _evidence(klipper_reachable=False, klipper_log=traceback)
    final = _evidence()  # recovery worked: reachable, no failed components, empty log
    decision = Decision(culprit="moonraker-notify", signal="notifier failed to import apprise",
                        fixer="moonraker-component")

    result = restart._recovery_result(["moonraker-notify"], decision, final, failure)

    assert result["ok"] is True
    output = result["log"][0]["items"][0]["output"]
    assert "ModuleNotFoundError: apprise" in output
    assert result["failure_log"] == output


def test_decide_blames_klipper_config_section() -> None:
    index = AttributionIndex(by_path={}, by_module={},
                             by_section={"temperature_sensor Rockchip": "cpu-temp"})
    evidence = _evidence(
        klipper_reachable=False, index=index,
        klipper_log="Section 'temperature_sensor Rockchip' is not a valid config section",
    )
    decision = decide(evidence, _ctx("cpu-temp"))
    assert decision.culprit == "cpu-temp"
    assert decision.fixer == "klipper-import"


def test_decide_reports_broker_down_as_not_a_plugin() -> None:
    decision = decide(_evidence(klipper_reachable=False, mqtt_up=False), _ctx(None, OperationKind.RECOVER))  # noqa: E501
    assert decision.culprit is None
    assert decision.fixer == "broker-down"
    assert "MQTT broker" in decision.signal


def test_decide_last_resort_blames_the_operated_plugin() -> None:
    decision = decide(_evidence(klipper_reachable=False, mqtt_up=True), _ctx("mystery"))
    assert decision.culprit == "mystery"
    assert decision.fixer == "last-resort"


def test_decide_catch_all_when_unattributable_and_no_target() -> None:
    decision = decide(_evidence(klipper_reachable=False, mqtt_up=True), _ctx(None, OperationKind.RECOVER))  # noqa: E501
    assert decision.culprit is None
    assert decision.fixer == "catch-all"
    assert decision.escaped is True
    assert "uninstalling" in decision.signal


def test_decide_skips_already_deactivated_then_falls_to_catch_all() -> None:
    index = AttributionIndex(by_path={}, by_module={}, by_section={"notifier phone": "moonraker-notify"})  # noqa: E501
    decision = decide(_evidence(failed_components=["notifier"], index=index), _ctx(),
                      already=["moonraker-notify"])
    assert decision.fixer == "catch-all"
    assert decision.escaped is True
