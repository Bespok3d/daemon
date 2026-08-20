# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Refusal cases the happy-path suite (test_auth.py, test_auth_props.py) does not cover.

The invariant: only an enrolled client commands the printer. Every near-miss on a bearer token
(empty, truncated, wrong case, padded with whitespace) must fall through to refused, and a torn or
malformed token store must refuse rather than let an exception escape the auth boundary."""
from pathlib import Path

import pytest

from core import auth

_STORED_TOKEN = "faketoken00000000000000000000ab"


@pytest.fixture
def isolated_acl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    acl_path = tmp_path / "acl.json"
    monkeypatch.setattr(auth, "ACL_PATH", acl_path)
    return acl_path


@pytest.fixture
def acl_with_stored_token(isolated_acl: Path) -> Path:
    isolated_acl.write_text(f'{{"keys": [], "roles": {{}}, "tokens": ["{_STORED_TOKEN}"]}}')
    return isolated_acl


def test_empty_token_never_authorizes(acl_with_stored_token: Path) -> None:
    """An empty bearer credential must be refused even though the store holds valid tokens."""
    assert auth.is_authorized_token("") is False


def test_truncated_token_is_refused(acl_with_stored_token: Path) -> None:
    """A prefix of a valid token (a stray truncation, a copy-paste cut short) is not the token."""
    truncated = _STORED_TOKEN[:-1]
    assert auth.is_authorized_token(truncated) is False


def test_wrong_case_token_is_refused(acl_with_stored_token: Path) -> None:
    """The compare is exact bytes; a same-value token in the wrong case must not pass."""
    assert auth.is_authorized_token(_STORED_TOKEN.upper()) is False


def test_token_padded_with_whitespace_is_refused(acl_with_stored_token: Path) -> None:
    """A trailing newline or space (a shell/env-var artifact) must not be silently trimmed."""
    assert auth.is_authorized_token(f"{_STORED_TOKEN}\n") is False
    assert auth.is_authorized_token(f" {_STORED_TOKEN}") is False


def test_revoked_identity_loses_key_authorization(isolated_acl: Path) -> None:
    """A client removed from the ACL must stop being an authorized key, not just lose its token."""
    auth.grant_key("stale-client-fingerprint", "fake-revoked-token-0000000000ab", "user", "Stale")
    auth.revoke_key("stale-client-fingerprint")
    assert auth.is_authorized("stale-client-fingerprint") is False


def test_corrupt_acl_file_refuses_instead_of_crashing_the_auth_check(isolated_acl: Path) -> None:
    """A torn write or a bad manual edit leaves acl.json holding text that is not valid JSON. The
    auth check on the request path must refuse the credential, never let json.JSONDecodeError
    escape past the auth boundary and turn a 401 into an unhandled server error."""
    isolated_acl.write_text("{not valid json")
    assert auth.is_authorized_token("any-token-at-all-0000000000000") is False
