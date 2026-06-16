"""HTTP and websocket routes, grouped by concern.

Each submodule owns one route group on its own `APIRouter`; this package aggregates them into the
single `router` that `api` mounts. Health checks and capabilities live in `health`, the websocket
live feeds in `feeds`, the streaming install route in `install`, the plain package command routes
(reconfigure/recover/update-batch/uninstall) in `packages`, deactivate/teardown in `lifecycle`, and
the access-control flow in `access`.
"""
from fastapi import APIRouter

from . import access, feeds, health, install, lifecycle, packages

router = APIRouter()
router.include_router(health.router)
router.include_router(feeds.router)
router.include_router(install.router)
router.include_router(packages.router)
router.include_router(lifecycle.router)
router.include_router(access.router)
