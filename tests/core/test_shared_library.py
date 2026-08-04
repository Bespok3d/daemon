# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
import sys
from pathlib import Path

import core
from core.shared_library import SHARED_PYTHON_DIR, ensure_shared_packages_importable

DAEMON_ROOT = Path(core.__file__).resolve().parents[1]
SHARED_PACKAGES_THE_DAEMON_IMPORTS = ("bespok3d_contract", "bespok3d_patch")


def test_importing_core_puts_the_shared_packages_on_the_path() -> None:
    assert str(SHARED_PYTHON_DIR) in sys.path


def test_the_path_is_where_the_app_uploads_the_shared_packages() -> None:
    assert SHARED_PYTHON_DIR.relative_to(DAEMON_ROOT) == Path("lib_bespok3d/python")


def test_the_checked_out_library_carries_every_package_the_daemon_imports() -> None:
    absent = [
        package
        for package in SHARED_PACKAGES_THE_DAEMON_IMPORTS
        if not (SHARED_PYTHON_DIR / package / "__init__.py").is_file()
    ]

    assert absent == [], f"the lib_bespok3d checkout is older than the daemon: {absent}"


def test_the_entry_is_added_once_however_often_it_is_asked_for() -> None:
    before = sys.path.count(str(SHARED_PYTHON_DIR))
    ensure_shared_packages_importable()
    assert sys.path.count(str(SHARED_PYTHON_DIR)) == before
