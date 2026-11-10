# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Bespok3d daemon: on-printer process.

Exposes FastAPI over HTTPS when a TLS cert is present (generated at enrollment).
Auth: every request must carry a bearer token from the ACL.
"""

from typing import Any

import uvicorn
from uvicorn.config import LOGGING_CONFIG

from api import app
from core.data_root import DATA_ROOT
from core.log_redaction import TokenRedactionFilter

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 4269
# The certificate lives under the daemon's own data root, wherever that root is. On the U1 that is
# /userdata/bespok3d; on a Klipper host it is the printer user's own $HOME/bespok3d. Spelling the
# U1's path here made a generic daemon carry one device's fact and serve plain HTTP everywhere else.
CERT_FILE = DATA_ROOT / "etc/daemon/server.crt"
KEY_FILE = DATA_ROOT / "etc/daemon/server.key"
TOKEN_REDACTION = "token_redaction"
CORE_LOGGER = "core"


def _ssl_kwargs() -> dict:
    if CERT_FILE.exists() and KEY_FILE.exists():
        return {"ssl_certfile": str(CERT_FILE), "ssl_keyfile": str(KEY_FILE)}
    return {}


def log_config() -> dict[str, Any]:
    """uvicorn's own logging, with every handler passing records through the token redaction, and
    the daemon's own `core` records (what the safety net decided) written beside them."""
    redacting_handlers = {
        name: {**handler, "filters": [TOKEN_REDACTION]}
        for name, handler in LOGGING_CONFIG["handlers"].items()
    }
    core_logger = {"handlers": ["default"], "level": "INFO", "propagate": False}
    return {
        **LOGGING_CONFIG,
        "filters": {TOKEN_REDACTION: {"()": TokenRedactionFilter}},
        "handlers": redacting_handlers,
        "loggers": {**LOGGING_CONFIG["loggers"], CORE_LOGGER: core_logger},
    }


def main() -> None:
    uvicorn.run(
        app,
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        log_level="info",
        log_config=log_config(),
        **_ssl_kwargs(),
    )


if __name__ == "__main__":
    main()
