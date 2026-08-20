# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What an unauthenticated stranger, or a file torn by a power cut, may do to auth.

/access/request takes no credential and the bearer header is whatever a caller chose to send, so
both are hostile input. Neither may take the printer's auth down: a bad credential is refused, a
torn file is read as empty, and the owner's app keeps working either way.

Every value here is obviously fake: no real token, no real fingerprint.
"""

import json
from pathlib import Path

import pytest

from core import access_requests, auth

FAKE_TOKEN = "faketoken0000000000"


@pytest.fixture(autouse=True)
def printer_auth_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(auth, "ACL_PATH", tmp_path / "acl.json")
    monkeypatch.setattr(access_requests, "PENDING_PATH", tmp_path / "pending.json")
    return tmp_path


def _printer_holds_one_token() -> None:
    auth.grant_key("fake-client-id", FAKE_TOKEN, role="admin", label="fake app")


@pytest.mark.parametrize("offered", ["tökén", "\U0001f600", "token\x00with-a-null", "", "ß" * 200])
def test_a_bearer_token_that_is_not_ascii_is_refused_not_crashed_on(offered: str) -> None:
    """An unauthenticated caller picks the header text, so a byte outside ASCII must come back as a
    refusal. Compared as text it raised instead, and the printer answered every request with a
    server error until that caller stopped."""
    _printer_holds_one_token()
    assert auth.is_authorized_token(offered) is False


def test_the_real_token_is_still_accepted() -> None:
    _printer_holds_one_token()
    assert auth.is_authorized_token(FAKE_TOKEN) is True


def test_a_stored_token_that_is_not_text_refuses_instead_of_crashing() -> None:
    """A hand edited or torn acl.json can hold anything; a caller must still get an answer."""
    auth.ACL_PATH.parent.mkdir(parents=True, exist_ok=True)
    auth.ACL_PATH.write_text(json.dumps({"keys": [], "roles": {}, "labels": {},
                                         "tokens": [7], "token_identity": {}}))
    assert auth.is_authorized_token(FAKE_TOKEN) is False


@pytest.mark.parametrize("torn", ["", "{", '{"identity": "fake"}', "[1, 2, 3]", "null"])
def test_a_torn_pending_file_reads_as_no_requests_waiting(torn: str) -> None:
    """Unguarded, one torn file left the printer refusing every access request and every grant, so
    the owner could not add a second app until someone deleted the file over SSH."""
    access_requests.PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    access_requests.PENDING_PATH.write_text(torn)
    assert access_requests.load_pending() == []


def test_a_request_still_records_after_the_torn_file_is_read() -> None:
    access_requests.PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    access_requests.PENDING_PATH.write_text("{ not json")

    assert access_requests.add_pending({"identity": "fake-client-id", "token": FAKE_TOKEN}) is True
    assert [entry["identity"] for entry in access_requests.load_pending()] == ["fake-client-id"]
