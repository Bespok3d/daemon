# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Refusal coverage for the jinni actuation seam (core/jinni_client/actuation.py, ADR-0037).

An actuation reply pairs one ActionResult back to each command the daemon sent, in order; a caller
(core/safety/restart_batch.py, core/packages/start_commands.py) zips its command list against that
reply to build its phase log. Nothing on the in-process path enforces the pairing: `dispatch.route`
returns whatever the jinni hands back and `cast()` in actuation.py is a type hint, never a runtime
check. A jinni that answers with fewer results than commands sent (a dropped queue slot, a malformed
reply) must be refused here, before a caller's zip() silently drops the missing command and reports
success for actions nobody accounted for.
"""
import pytest

import protocol
from core import jinni_client
from protocol import ActionResult
from tests.fakes import FakeKlipperJinni


def test_run_actions_refuses_a_reply_with_fewer_results_than_commands_sent(
    monkeypatch: pytest.MonkeyPatch, device_jinni: FakeKlipperJinni,
) -> None:
    def dropped_one_result(commands: list[str]) -> list[ActionResult]:
        return [ActionResult(ok=True, output="ran") for _ in commands[:-1]]

    monkeypatch.setattr(device_jinni, "run_actions", dropped_one_result)

    with pytest.raises(protocol.ProtocolError):
        jinni_client.run_actions(["echo first", "echo second"])
