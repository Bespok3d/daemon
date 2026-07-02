from fastapi import APIRouter, HTTPException

from core import auth
from core.data_root import DATA_ROOT

from ..schemas import (
    AccessActionResponse,
    AccessClient,
    AccessClientsResponse,
    AccessIdentityBody,
    AccessRequestBody,
    AccessRequestResponse,
    PendingClient,
)

router = APIRouter()

_CERT_PATH = DATA_ROOT / "etc/daemon/server.crt"


def _server_cert() -> str:
    return _CERT_PATH.read_text() if _CERT_PATH.exists() else ""


@router.post(
    "/access/request",
    response_model=AccessRequestResponse,
    summary="Request access to this printer (unauthenticated; an existing client must approve)",
)
async def access_request(body: AccessRequestBody) -> AccessRequestResponse:
    if not auth.valid_access_request(body.identity, body.token, body.label, body.public_key or ""):
        raise HTTPException(status_code=400, detail="invalid access request")
    entry = {"identity": body.identity, "label": body.label,
             "public_key": body.public_key or "", "token": body.token}
    if not auth.add_pending(entry):
        raise HTTPException(status_code=429, detail="too many pending access requests")
    return AccessRequestResponse(ok=True, cert=_server_cert())


@router.get(
    "/access/clients",
    response_model=AccessClientsResponse,
    summary="List authorized clients and pending access requests",
)
async def access_clients() -> AccessClientsResponse:
    return AccessClientsResponse(
        clients=[AccessClient(**client) for client in auth.list_clients()],
        pending=[PendingClient(**item) for item in auth.list_pending()],
    )


@router.post(
    "/access/grant",
    response_model=AccessActionResponse,
    summary="Approve a pending access request (any authorized client may grant)",
)
async def access_grant(body: AccessIdentityBody) -> AccessActionResponse:
    entry = auth.pop_pending(body.identity)
    if entry is None:
        raise HTTPException(status_code=404, detail="no such pending request")
    auth.grant_key(body.identity, entry["token"], role="user", label=entry.get("label", ""))
    return AccessActionResponse(ok=True)


@router.post(
    "/access/revoke",
    response_model=AccessActionResponse,
    summary="Remove an authorized client (any authorized client may revoke)",
)
async def access_revoke(body: AccessIdentityBody) -> AccessActionResponse:
    auth.revoke_key(body.identity)
    return AccessActionResponse(ok=True)
