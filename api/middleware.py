from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from core.auth import is_authorized_token

# /access/request is the one unauthenticated window: a not-yet-authorized client posts an access
# request that an existing client then approves. The pending cap in core.auth is its abuse limit.
_EXEMPT = frozenset({"/docs", "/redoc", "/openapi.json", "/access/request"})


class BearerTokenMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path in _EXEMPT:
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
        token = auth[len("Bearer "):]
        if not is_authorized_token(token):
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
        return await call_next(request)
