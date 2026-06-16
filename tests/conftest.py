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
    from tests.fakes import FakeGenericJinni
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
def plugin_root(tmp_path: Path) -> Path:
    root = tmp_path / "plugins"
    root.mkdir()
    return root
