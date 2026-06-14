from fastapi import APIRouter, HTTPException

from core import packages
from jinni.loader import get_jinni

from ..schemas import DeactivateResponse, TeardownResponse

router = APIRouter()


@router.post(
    "/deactivate",
    response_model=DeactivateResponse,
    summary="Deactivate all plugins without removing files",
)
async def deactivate() -> DeactivateResponse:
    jinni = get_jinni()
    try:
        packages.deactivate_all(jinni.paths())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DeactivateResponse(ok=True)


@router.post(
    "/teardown",
    response_model=TeardownResponse,
    summary="Uninstall all plugins and remove config hooks; SSH caller removes the workspace",
)
async def teardown() -> TeardownResponse:
    jinni = get_jinni()
    try:
        packages.teardown(jinni.paths())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TeardownResponse(ok=True)
