# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
# Here rather than in an entrypoint because every importer of the shared packages is a `core`
# module, and Python runs this before any of them: no import order to get wrong, on the printer
# or in a test.
from core.shared_library import ensure_shared_packages_importable

ensure_shared_packages_importable()
