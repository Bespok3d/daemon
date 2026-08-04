# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The road to the shared Bespok3d Python packages.

They deploy next to the daemon (the app uploads the whole `lib_bespok3d/python` tree with the rest
of the modules), so the path is derived from this file and never from an environment variable: an
already-enrolled printer keeps a launcher script written before this existed, and appending here
means the daemon finds the packages without the printer being re-enrolled."""
import sys
from pathlib import Path

SHARED_PYTHON_DIR = Path(__file__).resolve().parents[1] / "lib_bespok3d" / "python"


def ensure_shared_packages_importable() -> None:
    entry = str(SHARED_PYTHON_DIR)
    if entry not in sys.path:
        sys.path.append(entry)
