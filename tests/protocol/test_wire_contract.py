# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The request side of the daemon-jinni contract, and what the jinni is allowed to be asked.

`parse_request` is the jinni's front door: everything that reaches it came off a socket, so a torn
frame, a peer on another protocol version and a verb nobody agreed to must all come back as one
refusal the daemon can recycle on. The verb list is the whole of the reachable surface: if a name
outside it were callable, whoever can reach the socket could call any method the jinni happens to
have, which is how a plugin manager turns into a remote shell.
"""
import json

import pytest

from protocol import frame
from protocol.contracts import ServiceHealth
from protocol.wire import (
    CONTRACT_VERBS,
    PROTOCOL_VERSION,
    ProtocolError,
    error_bytes,
    parse_request,
    parse_result,
    request_bytes,
    result_bytes,
)

_A_VERB_ON_THE_CONTRACT = "health"
_NAMES_NOBODY_AGREED_TO = ["run_shell", "__init__", "eval", "", "HEALTH", "health ", None]


def _framed(message: dict) -> bytes:
    return frame.encode(message)


def test_a_request_the_daemon_built_is_read_back_as_the_verb_and_arguments_it_sent() -> None:
    verb, args = parse_request(request_bytes("run_actions", [["/etc/init.d/S61moonraker restart"]]))

    assert verb == "run_actions"
    assert args == [["/etc/init.d/S61moonraker restart"]]


def test_a_frame_torn_in_transit_is_refused_not_guessed_at() -> None:
    with pytest.raises(ProtocolError, match="unreadable request frame"):
        parse_request(b'{"v": 3, "verb": "hea' + frame.ETX)


@pytest.mark.parametrize("peer_version", [1, 2, 4, "3", None])
def test_a_peer_on_another_protocol_version_is_told_to_update_rather_than_obeyed(
    peer_version: object,
) -> None:
    """An adapter built against an older contract would be answered in a shape it cannot read; the
    printer's owner gets "update the adapter" instead of a jinni that misbehaves quietly."""
    with pytest.raises(ProtocolError, match="update the adapter"):
        parse_request(_framed({"v": peer_version, "verb": _A_VERB_ON_THE_CONTRACT, "args": []}))


@pytest.mark.parametrize("uninvited_name", _NAMES_NOBODY_AGREED_TO)
def test_only_a_verb_on_the_contract_can_be_asked_of_the_jinni(uninvited_name: object) -> None:
    with pytest.raises(ProtocolError, match="unknown verb"):
        parse_request(_framed({"v": PROTOCOL_VERSION, "verb": uninvited_name, "args": []}))


def test_every_verb_on_the_contract_is_accepted() -> None:
    accepted = [parse_request(_framed({"v": PROTOCOL_VERSION, "verb": verb, "args": []}))[0]
                for verb in sorted(CONTRACT_VERBS)]

    assert set(accepted) == set(CONTRACT_VERBS)


def test_a_request_with_no_arguments_at_all_reads_as_no_arguments() -> None:
    verb, args = parse_request(_framed({"v": PROTOCOL_VERSION, "verb": "paths"}))

    assert (verb, args) == ("paths", [])


def test_a_token_set_travels_as_a_sorted_list_so_both_sides_read_the_same_order() -> None:
    """Blocked actions are a set on both sides and JSON has no set, so the order is pinned here
    rather than left to whatever the sending process happened to hash."""
    encoded = json.loads(result_bytes(frozenset({"zebra", "alpha", "middle"})).rstrip(frame.ETX))

    assert encoded == {"ok": True, "result": ["alpha", "middle", "zebra"]}


def test_a_reported_shape_travels_as_its_fields() -> None:
    a_down_service = [ServiceHealth(ready=False, detail="down")]

    encoded = json.loads(result_bytes(a_down_service).rstrip(frame.ETX))

    assert encoded["result"] == [{"ready": False, "detail": "down",
                                 "failed_components": [], "warnings": []}]


def test_a_jinni_that_never_answered_is_refused_by_name_so_the_daemon_can_recycle_it() -> None:
    with pytest.raises(ProtocolError, match="no reply from the jinni for 'health'"):
        parse_result("health", None)


def test_an_error_the_jinni_reported_reaches_the_daemon_in_its_own_words() -> None:
    with pytest.raises(ProtocolError, match="the init script is missing"):
        parse_result("run_actions", error_bytes("the init script is missing"))


def test_an_error_frame_with_no_words_still_refuses() -> None:
    with pytest.raises(ProtocolError):
        parse_result("run_actions", _framed({"ok": False}))
