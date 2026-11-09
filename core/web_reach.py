# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Whether a web address answers when the printer itself asks it.

A plugin that talks to a server on the network (a Spoolman server, for one) talks to it from the
printer, so only the printer can tell whether the address the user typed works. The computer that
types it may sit on another network, or resolve the name differently.
"""
import asyncio

import httpx

# The whole try, every redirect included, ends inside this. Long enough for a server on the far side
# of a slow link, short enough that the person typing the address is still looking at the field, and
# well inside the time the app waits for the printer to answer.
ANSWER_TIMEOUT_SECONDS = 4.0


async def http_code_at(url: str) -> int | None:
    """The http code the address answers with, following redirects, or None when nothing answers."""
    try:
        async with asyncio.timeout(ANSWER_TIMEOUT_SECONDS):
            return await _final_status_code(url)
    except (TimeoutError, httpx.HTTPError, httpx.InvalidURL):
        return None


async def _final_status_code(url: str) -> int:
    """Only the status line is read, never the body. The proxy settings of the environment are
    ignored, because the service that will use the address does not go through them either.
    """
    async with (
        httpx.AsyncClient(follow_redirects=True, trust_env=False) as client,
        client.stream("GET", url) as response,
    ):
        return response.status_code
