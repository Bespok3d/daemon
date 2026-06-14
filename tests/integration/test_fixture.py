"""The Python half of the adapter test contract: resolve an adapter's testkit/fixture.json
placeholders against its jinni/paths.json, mirroring the TS loadFixture and the daemon's own
_expand semantics. The daemon integration layer uses this to build a fake-device workspace
skeleton from the adapter's own declaration, so the harness never hardcodes a specific device.
"""
import json
from pathlib import Path

import pytest


def _find_adapter_dir() -> Path | None:
    """Walk up from this file looking for the snapmaker-u1 adapter (repo layout independent)."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "adapters" / "snapmaker-u1"
        if (candidate / "testkit" / "fixture.json").exists():
            return candidate
    return None


ADAPTER_DIR = _find_adapter_dir()

# The adapter is a sibling repo; skip when absent (e.g. a daemon-only test container).
pytestmark = pytest.mark.skipif(ADAPTER_DIR is None, reason="adapter not present")


def _expand(value: str, paths: dict[str, str]) -> str:
    for key in sorted(paths, key=len, reverse=True):
        value = value.replace(f"${key}", paths[key])
    return value


def load_fixture(adapter_dir: Path) -> dict:
    paths = json.loads((adapter_dir / "jinni" / "paths.json").read_text())
    raw = json.loads((adapter_dir / "testkit" / "fixture.json").read_text())
    return {
        "ssh": raw["ssh"],
        "baseImage": raw["baseImage"],
        "skeleton": {
            "dirs": [_expand(entry, paths) for entry in raw["skeleton"]["dirs"]],
            "files": [
                {"path": _expand(item["path"], paths), "content": item["content"]}
                for item in raw["skeleton"]["files"]
            ],
        },
        "services": raw["services"],
        "postEnroll": {
            "dirs": [_expand(entry, paths) for entry in raw["postEnroll"]["dirs"]],
            "files": [_expand(entry, paths) for entry in raw["postEnroll"]["files"]],
        },
    }


def test_fixture_resolves_path_placeholders() -> None:
    assert ADAPTER_DIR is not None
    fixture = load_fixture(ADAPTER_DIR)
    assert "/userdata/bespok3d/bin" in fixture["postEnroll"]["dirs"]
    assert "/userdata/bespok3d/auth/acl.json" in fixture["postEnroll"]["files"]


def test_fixture_keeps_literal_paths_and_ssh() -> None:
    assert ADAPTER_DIR is not None
    fixture = load_fixture(ADAPTER_DIR)
    assert "/home/lava/klipper/klippy/extras" in fixture["skeleton"]["dirs"]
    assert fixture["ssh"]["port"] == 2222


def test_no_unresolved_placeholders_remain() -> None:
    assert ADAPTER_DIR is not None
    fixture = load_fixture(ADAPTER_DIR)
    resolved = (
        fixture["postEnroll"]["dirs"]
        + fixture["postEnroll"]["files"]
        + fixture["skeleton"]["dirs"]
    )
    assert all("$" not in path for path in resolved)
