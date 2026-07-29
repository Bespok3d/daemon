# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Building a .b3 in a test the way a real packer builds one.

The daemon refuses an archive carrying a member its manifest never listed, so a fixture that writes
members without listing them is not a package the daemon would ever see. This derives files[] from
the members it is handed, with the sha256 and mode the packer records, so a fixture passes the
enumeration and checksum checks for the right reason instead of by exemption.

doc/ is left unlisted here because that is what the packages on printers today look like: the legacy
shell packers never listed the doc tree.
"""

import hashlib
import io
import json
import zipfile
from collections.abc import Mapping

from core.packages.members import UNLISTED_BY_CONSTRUCTION, is_doc_member

Member = bytes | str


def _as_bytes(content: Member) -> bytes:
    return content if isinstance(content, bytes) else content.encode()


def _is_listable(name: str) -> bool:
    """The mirror of what the daemon requires a manifest to declare, read from the daemon itself so
    a fixture cannot drift into declaring more or less than the real rule asks for."""
    return (
        name not in UNLISTED_BY_CONSTRUCTION
        and not name.endswith("/")
        and not is_doc_member(name)
    )


def files_entries(members: Mapping[str, Member]) -> list[dict]:
    """The manifest files[] entries covering every member a manifest is able to list."""
    return [
        {
            "path": name,
            "sha256": hashlib.sha256(_as_bytes(content)).hexdigest(),
            "mode": "644",
        }
        for name, content in sorted(members.items())
        if _is_listable(name)
    ]


def with_declared_files(manifest: dict, members: Mapping[str, Member]) -> dict:
    """`manifest` with files[] filled in from `members`, unless it already declares its own.

    An empty files[] reads as "not declared yet, fill it in": fixtures across this suite carry one
    as a placeholder. A test that needs a package whose members and manifest genuinely disagree
    builds the zip itself rather than going through here."""
    return {**manifest, "files": manifest.get("files") or files_entries(members)}


def package_bytes(manifest: dict, members: Mapping[str, Member]) -> bytes:
    """A .b3 carrying `members`, with files[] filled in unless the caller declared its own."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("manifest.json", json.dumps(with_declared_files(manifest, members)))
        for name, content in members.items():
            package.writestr(name, _as_bytes(content))
    return buffer.getvalue()
