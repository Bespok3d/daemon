# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The two whole-printer ops, refused: turn every plugin off, and remove Bespok3d entirely.

Both restart the printer's core services, so both must be refused while a print is running rather
than taking the printer down under the user. These pin that refusal at the HTTP boundary the app
calls, in the tokens the app localizes.
"""
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from api import app
from core import access_requests, auth, packages

_ISSUED_TOKEN = "fake-issued-token-0000"
_A_RESTART_MID_PRINT = "/etc/init.d/S55klipper restart"
_BOTH_WHOLE_PRINTER_OPS = [("/deactivate", "deactivate_all"), ("/teardown", "teardown")]


@pytest.fixture(autouse=True)
def daemon_acl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    acl = {
        "keys": ["fake-owner"], "roles": {"fake-owner": "admin"}, "labels": {"fake-owner": "Owner"},
        "tokens": [_ISSUED_TOKEN], "token_identity": {_ISSUED_TOKEN: "fake-owner"},
    }
    (tmp_path / "acl.json").write_text(json.dumps(acl))
    monkeypatch.setattr(auth, "ACL_PATH", tmp_path / "acl.json")
    monkeypatch.setattr(access_requests, "PENDING_PATH", tmp_path / "pending.json")
    monkeypatch.delenv("BESPOK3D_DEV_OPEN", raising=False)


def _refusing(monkeypatch: pytest.MonkeyPatch, whole_printer_op: str, refusal: Exception) -> None:
    def refuse(*sent: object, **named: object) -> Any:
        raise refusal
    monkeypatch.setattr(packages, whole_printer_op, refuse)


async def _ask_the_printer(route: str) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
    ) as client:
        return await client.post(route, headers={"Authorization": f"Bearer {_ISSUED_TOKEN}"})


@pytest.mark.parametrize(("route", "whole_printer_op"), _BOTH_WHOLE_PRINTER_OPS)
async def test_a_whole_printer_op_is_refused_while_a_print_is_running(
    monkeypatch: pytest.MonkeyPatch, route: str, whole_printer_op: str,
) -> None:
    _refusing(monkeypatch, whole_printer_op,
              packages.BlockedActionError(frozenset({_A_RESTART_MID_PRINT})))

    response = await _ask_the_printer(route)

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "error": "blocked", "blocked_actions": [_A_RESTART_MID_PRINT],
    }


@pytest.mark.parametrize(("route", "whole_printer_op"), _BOTH_WHOLE_PRINTER_OPS)
async def test_a_whole_printer_op_that_cannot_run_says_why_in_the_printers_words(
    monkeypatch: pytest.MonkeyPatch, route: str, whole_printer_op: str,
) -> None:
    _refusing(monkeypatch, whole_printer_op, ValueError("no plugin directory on this printer"))

    response = await _ask_the_printer(route)

    assert response.status_code == 400
    assert response.json()["detail"] == "no plugin directory on this printer"
