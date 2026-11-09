# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True)
def in_process_jinni(monkeypatch: pytest.MonkeyPatch) -> None:
    """The daemon and the jinni are separate apps that talk over the socket; the daemon never
    imports the jinni runtime (ADR-0037: only the protocol crosses). In tests the in-process
    transport's jinni is INJECTED here, a duck-typed fake answering the protocol verbs the way a
    real jinni answers over the wire. The default is a generic box; a suite that needs a device
    jinni overrides `jinni_client.dispatch.get_jinni` itself (e.g. tests/core/conftest)."""
    from core import jinni_client
    from tests.fakes_generic import FakeGenericJinni
    fake = FakeGenericJinni()
    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", lambda: fake)


@pytest.fixture
def acl_path(tmp_path: Path) -> Path:
    return tmp_path / "acl.json"


@pytest.fixture
def acl_with_key(tmp_path: Path) -> tuple[Path, str]:
    fingerprint = "ABCD1234ABCD1234ABCD1234ABCD1234ABCD1234"
    path = tmp_path / "acl.json"
    path.write_text(json.dumps({"keys": [fingerprint], "roles": {fingerprint: "admin"}}))
    return path, fingerprint


@pytest.fixture
def daemon_acl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Not autouse: only a suite that calls the daemon as its approved owner wants this ACL, and it
    opts in with `pytestmark = pytest.mark.usefixtures("daemon_acl")`."""
    # Imported here, not at module top: the project modules resolve only after the sys.path insert.
    from core import access_requests, auth
    from tests.fake_owner import ISSUED_TOKEN, OWNER_KEY
    acl = {
        "keys": [OWNER_KEY], "roles": {OWNER_KEY: "admin"}, "labels": {OWNER_KEY: "Owner"},
        "tokens": [ISSUED_TOKEN], "token_identity": {ISSUED_TOKEN: OWNER_KEY},
    }
    (tmp_path / "acl.json").write_text(json.dumps(acl))
    monkeypatch.setattr(auth, "ACL_PATH", tmp_path / "acl.json")
    monkeypatch.setattr(access_requests, "PENDING_PATH", tmp_path / "pending.json")
    # Pin dev-open off so a token check never passes on a stray environment setting.
    monkeypatch.delenv("BESPOK3D_DEV_OPEN", raising=False)


@pytest.fixture
def plugin_root(tmp_path: Path) -> Path:
    root = tmp_path / "plugins"
    root.mkdir()
    return root
