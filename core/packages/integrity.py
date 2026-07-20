"""Integrity: verify a plugin's on-disk files against the sha256 the packer recorded in the
manifest, before any placement or ownership phase touches them. `b3-builder`'s `packPlugin` writes
`sha256` for every entry in `manifest["files"]` at pack time; this module is the daemon-side check
that closes the loop, so a corrupted or truncated `.b3` extraction is refused before it is wired
into the printer.
"""

import hashlib
from pathlib import Path

# Why the archive did not match its signed manifest. Relayed as TOKENS the client localizes
# (ADR-0037); the exception message spells them out for the daemon's own logs, never for the user.
CHECKSUM_MISMATCH = "checksum_mismatch"
UNDECLARED_MEMBER = "undeclared_member"
ESCAPING_MEMBER = "escaping_member"
ESCAPING_PLUGIN_ID = "escaping_plugin_id"


class IntegrityError(Exception):
    """Install was refused because the package did not match its signed manifest: a file whose
    sha256 differs, a member the manifest never listed, a member aimed outside the plugin dir, or a
    plugin name that is not a plain directory name."""

    def __init__(self, plugin_id: str, reason: str, paths: list[str]) -> None:
        self.plugin_id = plugin_id
        self.reason = reason
        self.paths = paths
        super().__init__(f"{plugin_id} failed integrity check ({reason}): {', '.join(paths)}")


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
