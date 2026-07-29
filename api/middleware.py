# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
import os
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from core.auth import is_authorized_token

# /access/request is the one unauthenticated command window: a not-yet-authorized client posts an
# access request that an existing client then approves. The pending cap in core.auth is its abuse
# limit. /license is read-only and open because the AGPL offer it carries is owed to anyone reaching
# this daemon over the network, which a token would defeat.
_EXEMPT = frozenset({"/docs", "/redoc", "/openapi.json", "/access/request", "/license"})


def _dev_open() -> bool:
    """DEV ONLY: scripts/serve-local.sh sets BESPOK3D_DEV_OPEN=1 so the local Swagger run answers
    with no token. A printer never sets it; tests never set it, so the 401 tests still pass."""
    return os.environ.get("BESPOK3D_DEV_OPEN") == "1"


class BearerTokenMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if _dev_open() or request.url.path in _EXEMPT:
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
        token = auth[len("Bearer "):]
        if not is_authorized_token(token):
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
        return await call_next(request)
