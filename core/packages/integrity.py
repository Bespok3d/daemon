"""Integrity: verify a plugin's on-disk files against the sha256 the packer recorded in the
manifest, before any placement or ownership phase touches them. `b3-builder`'s `packPlugin` writes
`sha256` for every entry in `manifest["files"]` at pack time; this module is the daemon-side check
that closes the loop, so a corrupted or truncated `.b3` extraction is refused before it is wired
into the printer.
"""

import hashlib
from pathlib import Path


class IntegrityError(Exception):
    """Install was refused because one or more files failed the manifest's sha256 check."""

    def __init__(self, plugin_id: str, mismatched: list[str]) -> None:
        self.plugin_id = plugin_id
        self.mismatched = mismatched
        super().__init__(f"{plugin_id} failed integrity check: {', '.join(mismatched)}")


def verify_files(plugin_dir: Path, manifest_files: list[dict]) -> list[str]:
    """Return the manifest paths whose on-disk file is missing or whose sha256 does not match."""
    return [entry["path"] for entry in manifest_files if not _matches(plugin_dir, entry)]


def _matches(plugin_dir: Path, entry: dict) -> bool:
    """An entry the packer never hashed cannot be vouched for, so a missing sha256 is a mismatch."""
    target = plugin_dir / entry["path"]
    recorded: object = entry.get("sha256")
    return target.exists() and recorded == _sha256(target)


def _sha256(target: Path) -> str:
    digest = hashlib.sha256()
    digest.update(target.read_bytes())
    return digest.hexdigest()
