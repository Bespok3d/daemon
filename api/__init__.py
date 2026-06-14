import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from core.packages import write_startup_control_scripts
from jinni.loader import get_jinni

from .middleware import BearerTokenMiddleware
from .routes import router

_CERT_FILE = Path("/userdata/bespok3d/etc/daemon/server.crt")
_on_printer = _CERT_FILE.exists()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    jinni = get_jinni()
    if _on_printer:
        write_startup_control_scripts(jinni, jinni.paths())
    tasks = [asyncio.create_task(coro) for coro in jinni.background_tasks()]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


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
