import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core import jinni_client
from core.data_root import DATA_ROOT
from core.packages import BlockedActionError
from core.printer_identity import ensure_printer_uuid

from .middleware import BearerTokenMiddleware
from .routes import router

_CERT_FILE = Path("/userdata/bespok3d/etc/daemon/server.crt")
_on_printer = _CERT_FILE.exists()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # The printer uuid is minted only where a persistent data root exists (a printer, the dev
    # serve's temp root); a bare test run has nowhere durable to keep it, /status reports null.
    if DATA_ROOT.is_dir():
        await asyncio.to_thread(ensure_printer_uuid)
    # On the printer the daemon spawns and parents the jinni child, then talks to it over the socket
    # (ADR-0037); the child does its own startup scripts and background tasks. In dev the seam stays
    # in-process. The spawn blocks on the handshake, so it runs off the event loop.
    process = await asyncio.to_thread(jinni_client.start_jinni) if _on_printer else None
    try:
        yield
    finally:
        if process is not None:
            jinni_client.stop_jinni(process)


app = FastAPI(
    title="Bespok3d daemon",
    version="0.1.0",
    description=(
        "On-printer daemon for the Bespok3d plugin manager. "
        "All routes require `Authorization: Bearer <token>`."
    ),
    docs_url=None if _on_printer else "/docs",
    redoc_url=None if _on_printer else "/redoc",
    lifespan=lifespan,
)
app.add_middleware(BearerTokenMiddleware)
app.include_router(router)


@app.exception_handler(BlockedActionError)
async def blocked_action_handler(_request: Request, exc: BlockedActionError) -> JSONResponse:
    """A refused op carries blocked-action TOKENS, never prose; the app localizes them."""
    return JSONResponse(
        status_code=409, content={"error": "blocked", "blocked_actions": exc.blocked},
    )
