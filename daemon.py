# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Bespok3d daemon: on-printer process.

Exposes FastAPI over HTTPS when a TLS cert is present (generated at enrollment).
Auth: every request must carry a bearer token from the ACL.
"""

from pathlib import Path

import uvicorn

from api import app

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 4269
CERT_FILE = Path("/userdata/bespok3d/etc/daemon/server.crt")
KEY_FILE = Path("/userdata/bespok3d/etc/daemon/server.key")


def _ssl_kwargs() -> dict:
    if CERT_FILE.exists() and KEY_FILE.exists():
        return {"ssl_certfile": str(CERT_FILE), "ssl_keyfile": str(KEY_FILE)}
    return {}


def main() -> None:
    uvicorn.run(
        app,
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        log_level="info",
        **_ssl_kwargs(),
    )


if __name__ == "__main__":
    main()
