# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""HTTP and websocket routes, grouped by concern.

Each submodule owns one route group on its own `APIRouter`; this package aggregates them into the
single `router` that `api` mounts. Health checks and capabilities live in `health`, the websocket
live feeds in `feeds`, the single-plugin commands (install/reconfigure/uninstall) under `/plugins/`
in `plugins`, an installed plugin's file hashes and file restore in `plugin_files`, the multipart
batch-apply commands (update-batch/install-batch) under `/packages/` in `batch`, the other pack
commands (recover/uninstall-batch) under `/packages/` in `packages`, the
narrow setup repair in `setup_repair`, deactivate/teardown in `lifecycle`, the access-control
flow in `access`, and the printer's own try of a web address in `reach`.
"""
from fastapi import APIRouter

from . import (
    access,
    batch,
    feeds,
    health,
    lifecycle,
    packages,
    plugin_files,
    plugin_install,
    plugins,
    reach,
    setup_repair,
)

router = APIRouter()
router.include_router(health.router)
router.include_router(feeds.router)
router.include_router(plugin_install.router)
router.include_router(plugins.router)
router.include_router(plugin_files.router)
router.include_router(batch.router)
router.include_router(packages.router)
router.include_router(setup_repair.router)
router.include_router(lifecycle.router)
router.include_router(access.router)
router.include_router(reach.router)
