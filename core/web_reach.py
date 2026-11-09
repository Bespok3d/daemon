# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Whether a web address answers when the printer itself asks it.

A plugin that talks to a server on the network (a Spoolman server, for one) talks to it from the
printer, so only the printer can tell whether the address the user typed works. The computer that
types it may sit on another network, or resolve the name differently.
"""
import httpx

# Long enough for a server on the far side of a slow link, short enough that the user typing the
# address is still looking at the field when the answer comes back.
ANSWER_TIMEOUT_SECONDS = 4.0


async def http_code_at(url: str) -> int | None:
    """The http code the address answers with, following redirects, or None when nothing answers.

    Only the status line is read, never the body. The proxy settings of the environment are ignored,
    because the service that will use the address does not go through them either.
    """
    try:
        async with (
            httpx.AsyncClient(
                timeout=ANSWER_TIMEOUT_SECONDS, follow_redirects=True, trust_env=False,
            ) as client,
            client.stream("GET", url) as response,
        ):
            return response.status_code
    except (httpx.HTTPError, httpx.InvalidURL):
        return None
