# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
import json
from pathlib import Path

from core.packages.machinery import DAEMON_PACKAGE
from core.packages.machinery_fingerprints import MACHINERY_MANIFEST_DIR, machinery_fingerprints

JINNI_PACKAGE = "bespok3d-jinni-snapmaker-u1"
DAEMON_FINGERPRINT = "cd" * 32
JINNI_FINGERPRINT = "ef" * 32
DAEMON_ROOT = Path(__file__).resolve().parents[3]


def keep_manifest(manifest_dir: Path, package_name: str, manifest_text: str) -> None:
    manifest_dir.mkdir(exist_ok=True)
    (manifest_dir / f"{package_name}.json").write_text(manifest_text)


def test_each_kept_manifest_reports_under_its_package_name(tmp_path: Path) -> None:
    keep_manifest(tmp_path, DAEMON_PACKAGE, json.dumps({"fingerprint": DAEMON_FINGERPRINT}))
    keep_manifest(tmp_path, JINNI_PACKAGE, json.dumps({"fingerprint": JINNI_FINGERPRINT}))
    assert machinery_fingerprints(tmp_path) == {
        DAEMON_PACKAGE: DAEMON_FINGERPRINT,
        JINNI_PACKAGE: JINNI_FINGERPRINT,
    }


def test_a_printer_never_given_the_manifests_reports_none(tmp_path: Path) -> None:
    assert machinery_fingerprints(tmp_path / "absent") == {}


def test_a_manifest_torn_by_a_cut_write_is_left_out(tmp_path: Path) -> None:
    keep_manifest(tmp_path, DAEMON_PACKAGE, '{"fingerprint": "cd')
    keep_manifest(tmp_path, JINNI_PACKAGE, json.dumps({"fingerprint": JINNI_FINGERPRINT}))
    assert machinery_fingerprints(tmp_path) == {JINNI_PACKAGE: JINNI_FINGERPRINT}


def test_a_package_packed_before_fingerprints_existed_is_left_out(tmp_path: Path) -> None:
    keep_manifest(tmp_path, DAEMON_PACKAGE, json.dumps({"version": "0.15.0"}))
    assert machinery_fingerprints(tmp_path) == {}


def test_a_fingerprint_that_is_not_text_is_left_out(tmp_path: Path) -> None:
    keep_manifest(tmp_path, DAEMON_PACKAGE, json.dumps({"fingerprint": 42}))
    assert machinery_fingerprints(tmp_path) == {}


def test_a_manifest_that_is_not_an_object_is_left_out(tmp_path: Path) -> None:
    keep_manifest(tmp_path, DAEMON_PACKAGE, json.dumps([DAEMON_FINGERPRINT]))
    assert machinery_fingerprints(tmp_path) == {}


def test_a_file_that_is_not_a_kept_manifest_is_ignored(tmp_path: Path) -> None:
    stray_copy = tmp_path / f"{DAEMON_PACKAGE}.json.tmp"
    stray_copy.write_text(json.dumps({"fingerprint": DAEMON_FINGERPRINT}))
    (tmp_path / f"{JINNI_PACKAGE}.json").mkdir()
    assert machinery_fingerprints(tmp_path) == {}


# The adapter writes the manifests to <the directory the daemon's files land in>/manifests, so the
# daemon must look beside its own files (the directory holding its published manifest.json), not
# under its data root.
def test_the_manifests_are_read_beside_the_daemon_files() -> None:
    assert (DAEMON_ROOT / "manifest.json").is_file()
    assert MACHINERY_MANIFEST_DIR == DAEMON_ROOT / "manifests"
