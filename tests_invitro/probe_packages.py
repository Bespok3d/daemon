# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The throwaway packages this suite offers a real printer.

Three of them are built to be refused, one is the smallest thing a printer can accept. They are
built the way the packer builds a package (files[] derived from the members, checksums and all), so
a refusal here happens for the reason the test names and never because the fixture was malformed.

Every id and value is obviously fake: nothing here can be mistaken for a plugin someone published.
"""
from tests.package_fixtures import package_bytes
from tests.zip_declaration import unpacked_sizes_declared_as

PROBE_PLUGIN_ID = "invitro-probe"
PROBE_VERSION = "0.0.1"
PROBE_FILE = "files/probe.txt"
PROBE_CONTENT = "written by the daemon in-vitro suite; safe to delete\n"
REQUIREMENTS_MEMBER = "requirements.txt"
UNBAKED_DEPENDENCY = "a-dependency-this-package-never-baked==0.0.1\n"
UNKNOWN_MANIFEST_KEY = "a_key_no_daemon_has_ever_read"
DAEMON_FLOOR_NO_PRINTER_MEETS = "99.0.0"
UNPACKED_SIZE_PER_MEMBER = 4_000_000_000
MEMBERS_DECLARING_MORE_THAN_ANY_FLASH_HOLDS = 64
MANIFEST_MEMBER = "manifest.json"
UNPACKED_SIZE_DECLARED_BY_A_LYING_MEMBER = 100
CONTENT_REALLY_IN_THE_STREAM = "x" * 200_000


def _probe_manifest(**declared: object) -> dict:
    return {
        "name": PROBE_PLUGIN_ID,
        "version": PROBE_VERSION,
        "install": {"dirs": [], "symlinks": [], "patches": []},
        **declared,
    }


def package_asking_for_a_daemon_no_printer_runs() -> bytes:
    """Declares a daemon floor above every daemon there is, so the printer refuses it outright."""
    return package_bytes(
        _probe_manifest(min_daemon_version=DAEMON_FLOOR_NO_PRINTER_MEETS),
        {PROBE_FILE: PROBE_CONTENT},
    )


def package_declaring_more_bytes_than_the_flash_holds() -> bytes:
    """Claims to unpack to hundreds of gigabytes while carrying a few hundred, so the printer
    refuses it for the space it would need and no printer is ever asked to write those bytes."""
    fillers = {
        f"files/filler-{position:02d}.bin": PROBE_CONTENT
        for position in range(MEMBERS_DECLARING_MORE_THAN_ANY_FLASH_HOLDS)
    }
    honest_package = package_bytes(_probe_manifest(), fillers)
    return unpacked_sizes_declared_as(
        honest_package, UNPACKED_SIZE_PER_MEMBER, left_alone={MANIFEST_MEMBER},
    )


def package_declaring_python_deps_it_never_baked() -> bytes:
    """Ships a requirements file with no baked wheels beside it, which is a broken build: the
    printer never pips, so the dependency would simply be missing at runtime."""
    return package_bytes(
        _probe_manifest(),
        {PROBE_FILE: PROBE_CONTENT, REQUIREMENTS_MEMBER: UNBAKED_DEPENDENCY},
    )


def package_carrying_a_manifest_key_the_daemon_does_not_know() -> bytes:
    """Carries a key no daemon reads. A newer packer adding a field must not brick an older printer,
    so this one is expected to install."""
    return package_bytes(
        _probe_manifest(**{UNKNOWN_MANIFEST_KEY: "a value no daemon has ever read"}),
        {PROBE_FILE: PROBE_CONTENT},
    )


def package_whose_member_unpacks_to_more_than_it_declared() -> bytes:
    """Declares a hundred bytes for a member carrying two hundred thousand. No check before the
    write can see that, so the printer has to stop mid write and take the part written tree back
    off itself. The printer never writes more than the hundred bytes the member declared."""
    honest_package = package_bytes(_probe_manifest(), {PROBE_FILE: CONTENT_REALLY_IN_THE_STREAM})
    return unpacked_sizes_declared_as(
        honest_package,
        UNPACKED_SIZE_DECLARED_BY_A_LYING_MEMBER,
        left_alone={MANIFEST_MEMBER},
    )
