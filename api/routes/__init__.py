"""HTTP and websocket routes, grouped by concern.

Each submodule owns one route group on its own `APIRouter`; this package aggregates them into the
single `router` that `api` mounts. Health checks and capabilities live in `health`, the websocket
live feeds in `feeds`, the package command routes in `packages`, deactivate/teardown in `lifecycle`,
and the access-control flow in `access`.
"""
from fastapi import APIRouter

from . import access, feeds, health, lifecycle, packages

router = APIRouter()
router.include_router(health.router)
router.include_router(feeds.router)
router.include_router(packages.router)
router.include_router(lifecycle.router)
router.include_router(access.router)
