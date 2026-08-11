# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Guard: a `daemon-v<version>` release tag must carry the version the tree it builds reports.

The release workflow fires on the tag, but everything it publishes is stamped from `version.py`:
the package filename, the GitHub release, and the index atom the app reads to learn a newer daemon
exists. A tag whose number disagrees therefore publishes a package the tag lies about, and the
disagreement is invisible afterwards. Refuse the run instead.

Refusing a ref that is not a `daemon-v*` tag at all is the same guard from the other side: that is
what a run off a branch looks like, and a branch must never publish.
"""
import runpy
import sys
from pathlib import Path

TAG_PREFIX = "daemon-v"
VERSION_MODULE = Path(__file__).resolve().parent.parent / "version.py"


def declared_daemon_version() -> str:
    """DAEMON_VERSION as version.py declares it, read by path so the guard needs no import path."""
    return str(runpy.run_path(str(VERSION_MODULE))["DAEMON_VERSION"])


def tag_version(ref_name: str) -> str | None:
    """The version a `daemon-v<version>` tag claims, or None when the ref is not one of those."""
    if not ref_name.startswith(TAG_PREFIX):
        return None
    return ref_name[len(TAG_PREFIX):]


def main(argv: list[str]) -> int:
    ref_name = argv[1] if len(argv) > 1 else ""
    claimed = tag_version(ref_name)
    if claimed is None:
        print(f"'{ref_name}' is not a {TAG_PREFIX}* tag: a daemon release is published by a "
              "version tag and by nothing else", file=sys.stderr)
        return 1
    declared = declared_daemon_version()
    if claimed != declared:
        print(f"tag '{ref_name}' claims {claimed} but version.py declares {declared}: the package "
              f"would be published as {declared}", file=sys.stderr)
        return 1
    print(f"tag '{ref_name}' matches DAEMON_VERSION {declared}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
