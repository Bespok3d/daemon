# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Keep access tokens out of the daemon log.

The app opens the WebSocket feeds with the token in the URL, and uvicorn logs every handshake and
request with its query string. The log is readable on the printer, so a logged token is a lifted
token.
"""

import logging
import re

# The marker carries no "token=", so a grep for it on the printer finds only what slipped through.
REDACTED = "[token redacted]"
_TOKEN_PARAMETER = re.compile(r'token=[^&\s"#]*')


def redact_tokens(log_text: str) -> str:
    """The text with every `token=` parameter replaced, the rest of the line kept readable."""
    return _TOKEN_PARAMETER.sub(REDACTED, log_text)


def _redact_argument(argument: object) -> object:
    return redact_tokens(argument) if isinstance(argument, str) else argument


class TokenRedactionFilter(logging.Filter):
    """Redacts each record before any handler writes it. uvicorn's access formatter reads the
    request path straight from the record's arguments, so those are redacted one by one, not only
    the message. A traceback is rendered here, once, so the redacted text is what the formatter
    reuses."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact_argument(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(_redact_argument(argument) for argument in record.args)
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact_tokens(record.exc_text)
        return True
