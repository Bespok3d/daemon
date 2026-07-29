# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
import json
from pathlib import Path

import pytest

from core import auth


def test_load_acl_returns_empty_when_file_is_missing(
    acl_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth, "ACL_PATH", acl_path)
    result = auth.load_acl()
    assert result == {"keys": [], "roles": {}, "labels": {}, "tokens": [], "token_identity": {}}


def test_load_acl_parses_a_valid_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    acl_path = tmp_path / "acl.json"
    acl_path.write_text(json.dumps({"keys": ["FP1"], "roles": {"FP1": "admin"}}))
    monkeypatch.setattr(auth, "ACL_PATH", acl_path)

    result = auth.load_acl()

    assert result["keys"] == ["FP1"]
    assert result["roles"]["FP1"] == "admin"


def test_is_authorized_returns_true_for_known_fingerprint(
    acl_with_key: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    acl_path, fingerprint = acl_with_key
    monkeypatch.setattr(auth, "ACL_PATH", acl_path)
    assert auth.is_authorized(fingerprint) is True


def test_is_authorized_returns_false_for_unknown_fingerprint(
    acl_with_key: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    acl_path, _ = acl_with_key
    monkeypatch.setattr(auth, "ACL_PATH", acl_path)
    assert auth.is_authorized("UNKNOWN_FINGERPRINT_0000000000000000000") is False


def test_is_authorized_returns_false_when_acl_is_missing(
    acl_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth, "ACL_PATH", acl_path)
    assert auth.is_authorized("ANY_FINGERPRINT") is False


def test_is_authorized_token_returns_true_for_valid_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    acl_path = tmp_path / "acl.json"
    acl_path.write_text(
        json.dumps({"keys": [], "roles": {}, "tokens": ["valid-token-hex"]})
    )
    monkeypatch.setattr(auth, "ACL_PATH", acl_path)
    assert auth.is_authorized_token("valid-token-hex") is True


def test_is_authorized_token_returns_false_for_unknown_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    acl_path = tmp_path / "acl.json"
    acl_path.write_text(
        json.dumps({"keys": [], "roles": {}, "tokens": ["valid-token-hex"]})
    )
    monkeypatch.setattr(auth, "ACL_PATH", acl_path)
    assert auth.is_authorized_token("bad-token") is False


def test_is_authorized_token_returns_false_when_acl_is_missing(
    acl_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth, "ACL_PATH", acl_path)
    assert auth.is_authorized_token("any-token") is False


@pytest.fixture
def acl_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "ACL_PATH", tmp_path / "acl.json")
    monkeypatch.setattr(auth, "PENDING_PATH", tmp_path / "pending.json")


def test_grant_appends_without_clobbering_existing_keys(acl_files: None) -> None:
    auth.grant_key("alice", "tok-a", role="admin", label="Alice")
    auth.grant_key("bob", "tok-b", role="user", label="Bob")
    acl = auth.load_acl()
    assert acl["keys"] == ["alice", "bob"]
    assert auth.is_authorized_token("tok-a")
    assert auth.is_authorized_token("tok-b")


def test_revoke_removes_only_the_targets_key_and_token(acl_files: None) -> None:
    auth.grant_key("alice", "tok-a", "admin", "Alice")
    auth.grant_key("bob", "tok-b", "user", "Bob")
    auth.revoke_key("bob")
    assert not auth.is_authorized_token("tok-b")
    assert auth.is_authorized_token("tok-a")
    assert [client["identity"] for client in auth.list_clients()] == ["alice"]


def test_list_clients_never_exposes_tokens(acl_files: None) -> None:
    auth.grant_key("alice", "tok-a", "admin", "Alice")
    clients = auth.list_clients()
    assert clients == [{"identity": "alice", "role": "admin", "label": "Alice"}]
    assert "tok-a" not in json.dumps(clients)


def test_pending_roundtrip_keeps_token_only_for_pop(acl_files: None) -> None:
    assert auth.add_pending({"identity": "carol", "label": "Carol", "token": "tok-c"})
    listed = auth.list_pending()
    assert listed[0]["identity"] == "carol"
    assert "token" not in listed[0]
    popped = auth.pop_pending("carol")
    assert popped is not None and popped["token"] == "tok-c"
    assert auth.list_pending() == []


def test_add_pending_is_capped(acl_files: None) -> None:
    for index in range(auth.PENDING_CAP):
        assert auth.add_pending({"identity": f"id-{index}", "label": "x", "token": f"t-{index}"})
    assert not auth.add_pending({"identity": "overflow", "label": "x", "token": "t-x"})


def test_add_pending_dedupes_by_identity(acl_files: None) -> None:
    auth.add_pending({"identity": "carol", "label": "old", "token": "t1"})
    auth.add_pending({"identity": "carol", "label": "new", "token": "t2"})
    pending = auth.list_pending()
    assert len(pending) == 1
    assert pending[0]["label"] == "new"


def test_valid_access_request_accepts_a_normal_request() -> None:
    assert auth.valid_access_request("client-abc123", "a" * 64, "My Laptop", "")


def test_valid_access_request_rejects_injection_and_oversized_input() -> None:
    token = "a" * 64
    assert not auth.valid_access_request("evil;rm -rf /", token, "ok", "")
    assert not auth.valid_access_request("client-abc", "short", "ok", "")
    assert not auth.valid_access_request("client-abc", token, "line\nbreak", "")
    assert not auth.valid_access_request("client-abc", token, "x" * 100, "")
    assert not auth.valid_access_request("client-abc", token, "ok", "k" * 9000)
