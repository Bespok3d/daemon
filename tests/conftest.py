import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


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
