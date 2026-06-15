from fastapi import APIRouter, HTTPException

from core import jinni_client, packages

from ..schemas import DeactivateResponse, TeardownResponse

router = APIRouter()


@router.post(
    "/deactivate",
    response_model=DeactivateResponse,
    summary="Deactivate all plugins without removing files",
)
async def deactivate() -> DeactivateResponse:
    try:
        packages.deactivate_all(jinni_client.paths())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DeactivateResponse(ok=True)


@router.post(
    "/teardown",
    response_model=TeardownResponse,
    summary="Uninstall all plugins and remove config hooks; SSH caller removes the workspace",
)
async def teardown() -> TeardownResponse:
    try:
        packages.teardown(jinni_client.paths())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TeardownResponse(ok=True)
