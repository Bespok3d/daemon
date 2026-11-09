# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
from fastapi import APIRouter

from core.web_reach import http_code_at

from ..schemas import WebReachBody, WebReachResponse

router = APIRouter()


@router.post(
    "/net/reach",
    response_model=WebReachResponse,
    summary="Try a web address from the printer",
    description=(
        "Read-only. Asks the address once from the printer and reports the http code it answered "
        "with, so the app can tell the user whether a service address works from where the plugin "
        "will use it, not from the computer."
    ),
)
async def web_reach(body: WebReachBody) -> WebReachResponse:
    return WebReachResponse(http_code=await http_code_at(body.url))
