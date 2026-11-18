# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
import threading

import pytest

import protocol
from core.watch import rebooting, remedies
from core.watch.hub import WatchFrame
from core.watch.settings import RemedyChoice
from tests.core.watch.conftest import TimerTracker
from tests.core.watch.fake_watch import (
    STUCK_TOKEN,
    FakeWatchJinni,
    RecordingHub,
    RefusingRebootJinni,
    use_jinni,
)

pytestmark = pytest.mark.usefixtures("quick_reboot")

BUSY_PRINTER_BLOCKS = frozenset({"restart-klipper"})


class StillReportedHub(RecordingHub):
    """Records, for each frame, whether the stuck state was still reported as needing a power
    cycle when the app was told."""

    def __init__(self) -> None:
        super().__init__()
        self.reported_when_told: list[list[str]] = []

    def publish(self, frame: WatchFrame) -> None:
        self.reported_when_told.append(rebooting.not_being_cleared([STUCK_TOKEN]))
        super().publish(frame)


class ClosedLoopHub(RecordingHub):
    """A hub whose event loop closed while a frame was on its way, as at daemon shutdown."""

    def publish(self, frame: WatchFrame) -> None:
        raise RuntimeError("event loop is closed")


class PrintStartsDuringGraceJinni(FakeWatchJinni):
    """Idle when the remedy is chosen, printing by the time the grace is over."""

    def __init__(self) -> None:
        super().__init__()
        self.busy_checks = 0

    def blocked_actions(self) -> frozenset[str]:
        self.busy_checks += 1
        return frozenset() if self.busy_checks == 1 else BUSY_PRINTER_BLOCKS


class StateUnreadableAfterGraceJinni(PrintStartsDuringGraceJinni):
    """Idle when the remedy is chosen; its state cannot be read once the grace is over."""

    def blocked_actions(self) -> frozenset[str]:
        if super().blocked_actions():
            raise protocol.ProtocolError("state unreadable")
        return frozenset()


class BrokenRebootJinni(FakeWatchJinni):
    """A jinni that fails in an unexpected way when asked for the reboot."""

    def reboot_printer(self) -> None:
        raise OSError("jinni socket gone")


class UnreadableStateJinni(FakeWatchJinni):
    def blocked_actions(self) -> frozenset[str]:
        raise protocol.ProtocolError("state unreadable")


def apply_while_watching(remedy: RemedyChoice, hub: RecordingHub) -> None:
    remedies.apply_remedy(STUCK_TOKEN, remedy, hub, threading.Event())


def assert_reboot_taken_back(hub: RecordingHub) -> None:
    """The app was told of a reboot, then told it is taken back, and the state asks for a power
    cycle again."""
    [announced, taken_back] = hub.frames
    assert announced == {"token": STUCK_TOKEN, "remedy": "reboot", "id": announced["id"]}
    assert announced["id"]
    assert taken_back == {"token": STUCK_TOKEN, "remedy": "notify", "id": announced["id"]}
    assert rebooting.not_being_cleared([STUCK_TOKEN]) == [STUCK_TOKEN]


def test_notify_tells_the_app_and_never_reboots(monkeypatch: pytest.MonkeyPatch) -> None:
    jinni = use_jinni(monkeypatch, FakeWatchJinni())
    hub = RecordingHub()
    apply_while_watching("notify", hub)
    assert hub.frames == [{"token": STUCK_TOKEN, "remedy": "notify"}]
    assert jinni.reboots_asked == 0


def test_reboot_when_idle_only_notifies_while_the_printer_blocks_an_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jinni = use_jinni(monkeypatch, FakeWatchJinni(blocked=BUSY_PRINTER_BLOCKS))
    hub = RecordingHub()
    apply_while_watching("reboot-when-idle", hub)
    assert hub.frames == [{"token": STUCK_TOKEN, "remedy": "notify"}]
    assert jinni.reboots_asked == 0


def test_reboot_when_idle_announces_the_reboot_then_reboots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jinni = use_jinni(monkeypatch, FakeWatchJinni())
    hub = RecordingHub()
    apply_while_watching("reboot-when-idle", hub)
    [announced] = hub.frames
    assert announced == {"token": STUCK_TOKEN, "remedy": "reboot", "id": announced["id"]}
    assert jinni.reboots_asked == 1


def test_each_reboot_has_its_own_id(monkeypatch: pytest.MonkeyPatch) -> None:
    use_jinni(monkeypatch, RefusingRebootJinni())
    hub = RecordingHub()
    apply_while_watching("reboot-when-idle", hub)
    apply_while_watching("reboot-when-idle", hub)
    [first, _, second, _] = hub.frames
    assert first["id"] != second["id"]


def test_reboot_when_idle_stops_asking_for_a_power_cycle_before_the_app_hears_of_the_reboot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_jinni(monkeypatch, FakeWatchJinni())
    hub = StillReportedHub()
    apply_while_watching("reboot-when-idle", hub)
    assert hub.reported_when_told == [[]]
    assert rebooting.not_being_cleared([STUCK_TOKEN]) == []


def test_an_accepted_reboot_is_taken_back_only_once_it_is_overdue(
    monkeypatch: pytest.MonkeyPatch, reboot_timers: TimerTracker,
) -> None:
    use_jinni(monkeypatch, FakeWatchJinni())
    apply_while_watching("reboot-when-idle", RecordingHub())
    [timer] = reboot_timers.timers
    assert timer.interval == remedies.REBOOT_DUE_WITHIN_S
    assert timer.daemon


def test_a_printer_still_up_after_accepting_the_reboot_asks_for_a_power_cycle_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_jinni(monkeypatch, FakeWatchJinni())
    monkeypatch.setattr(remedies, "REBOOT_DUE_WITHIN_S", 0)
    hub = RecordingHub()
    apply_while_watching("reboot-when-idle", hub)
    hub.wait_for_frames(2)
    assert_reboot_taken_back(hub)


def test_a_reboot_that_cannot_be_asked_for_asks_for_a_power_cycle_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_jinni(monkeypatch, RefusingRebootJinni())
    hub = RecordingHub()
    apply_while_watching("reboot-when-idle", hub)
    assert_reboot_taken_back(hub)


def test_a_reboot_that_fails_unexpectedly_is_taken_back(monkeypatch: pytest.MonkeyPatch) -> None:
    use_jinni(monkeypatch, BrokenRebootJinni())
    hub = RecordingHub()
    with pytest.raises(OSError):
        apply_while_watching("reboot-when-idle", hub)
    assert_reboot_taken_back(hub)


def test_a_print_started_during_the_grace_is_never_cut_off(monkeypatch: pytest.MonkeyPatch) -> None:
    jinni = use_jinni(monkeypatch, PrintStartsDuringGraceJinni())
    hub = RecordingHub()
    apply_while_watching("reboot-when-idle", hub)
    assert jinni.reboots_asked == 0
    assert_reboot_taken_back(hub)


class StopOnAnnounceHub(RecordingHub):
    """Stops the watch as soon as the reboot is announced, as a setting change during the grace."""

    def __init__(self, stopping: threading.Event) -> None:
        super().__init__()
        self.stopping = stopping

    def publish(self, frame: WatchFrame) -> None:
        super().publish(frame)
        self.stopping.set()


def test_a_watch_stopped_during_the_grace_never_reboots(monkeypatch: pytest.MonkeyPatch) -> None:
    jinni = use_jinni(monkeypatch, FakeWatchJinni())
    monkeypatch.setattr(remedies, "REBOOT_NOTICE_GRACE_S", 60)
    stopping = threading.Event()
    hub = StopOnAnnounceHub(stopping)
    remedies.apply_remedy(STUCK_TOKEN, "reboot-when-idle", hub, stopping)
    assert jinni.reboots_asked == 0
    assert_reboot_taken_back(hub)


def test_a_watch_already_stopping_never_announces_a_reboot(monkeypatch: pytest.MonkeyPatch) -> None:
    jinni = use_jinni(monkeypatch, FakeWatchJinni())
    stopping = threading.Event()
    stopping.set()
    hub = RecordingHub()
    remedies.apply_remedy(STUCK_TOKEN, "reboot-when-idle", hub, stopping)
    assert hub.frames == [{"token": STUCK_TOKEN, "remedy": "notify"}]
    assert jinni.reboots_asked == 0


def test_a_state_seen_again_while_its_reboot_is_under_way_gets_no_second_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jinni = use_jinni(monkeypatch, FakeWatchJinni())
    hub = RecordingHub()
    apply_while_watching("reboot-when-idle", hub)
    apply_while_watching("reboot-when-idle", hub)
    apply_while_watching("notify", hub)
    [announced] = hub.frames
    assert announced["remedy"] == "reboot"
    assert jinni.reboots_asked == 1


def test_a_take_back_asks_for_a_power_cycle_again_before_the_app_hears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_jinni(monkeypatch, RefusingRebootJinni())
    hub = StillReportedHub()
    apply_while_watching("reboot-when-idle", hub)
    assert hub.reported_when_told == [[], [STUCK_TOKEN]]


def test_a_reboot_that_could_not_be_announced_never_happens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jinni = use_jinni(monkeypatch, FakeWatchJinni())
    with pytest.raises(RuntimeError):
        apply_while_watching("reboot-when-idle", ClosedLoopHub())
    assert jinni.reboots_asked == 0
    assert rebooting.not_being_cleared([STUCK_TOKEN]) == [STUCK_TOKEN]


def test_a_printer_whose_state_cannot_be_read_after_the_grace_is_never_rebooted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jinni = use_jinni(monkeypatch, StateUnreadableAfterGraceJinni())
    hub = RecordingHub()
    apply_while_watching("reboot-when-idle", hub)
    assert jinni.reboots_asked == 0
    assert_reboot_taken_back(hub)


def test_a_printer_whose_state_cannot_be_read_is_never_rebooted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jinni = use_jinni(monkeypatch, UnreadableStateJinni())
    hub = RecordingHub()
    apply_while_watching("reboot-when-idle", hub)
    assert hub.frames == [{"token": STUCK_TOKEN, "remedy": "notify"}]
    assert jinni.reboots_asked == 0


def test_notify_keeps_asking_for_a_power_cycle(monkeypatch: pytest.MonkeyPatch) -> None:
    use_jinni(monkeypatch, FakeWatchJinni())
    apply_while_watching("notify", RecordingHub())
    assert rebooting.not_being_cleared([STUCK_TOKEN]) == [STUCK_TOKEN]
