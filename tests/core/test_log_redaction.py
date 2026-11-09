# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""No access token reaches the daemon log.

Each line is emitted through uvicorn's own loggers with the format uvicorn uses, under the logging
config the daemon starts with, and what its handlers write is read back.
"""
import io
import logging
import logging.config
from collections.abc import Iterator

import pytest

from daemon import log_config

FEED_TOKEN = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
CLIENT = "10.6.9.4:55925"
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def _logger_state(logger: logging.Logger) -> tuple[list[logging.Handler], int, bool]:
    return logger.handlers[:], logger.level, logger.propagate


def _restore_logger(logger: logging.Logger, state: tuple[list[logging.Handler], int, bool]) -> None:
    logger.handlers, logger.level, logger.propagate = state


@pytest.fixture
def daemon_log() -> Iterator[io.StringIO]:
    """The text the daemon's log handlers write, while the daemon's logging config is in force."""
    loggers = [logging.getLogger(name) for name in UVICORN_LOGGERS]
    saved_states = [_logger_state(logger) for logger in loggers]
    logging.config.dictConfig(log_config())
    written = io.StringIO()
    stream_handlers = [handler for logger in loggers for handler in logger.handlers
                       if isinstance(handler, logging.StreamHandler)]
    for handler in stream_handlers:
        handler.setStream(written)
    yield written
    for logger, state in zip(loggers, saved_states, strict=True):
        _restore_logger(logger, state)


def test_an_accepted_feed_handshake_logs_the_path_without_the_token(
    daemon_log: io.StringIO,
) -> None:
    feed_url = f"/ws/install-progress?token={FEED_TOKEN}"

    logging.getLogger("uvicorn.error").info('%s - "WebSocket %s" [accepted]', CLIENT, feed_url)

    assert FEED_TOKEN not in daemon_log.getvalue()
    assert '"WebSocket /ws/install-progress?[token redacted]" [accepted]' in daemon_log.getvalue()


def test_a_refused_feed_handshake_logs_no_token(daemon_log: io.StringIO) -> None:
    feed_url = f"/ws/print-state?token={FEED_TOKEN}"

    logging.getLogger("uvicorn.error").info('%s - "WebSocket %s" 403', CLIENT, feed_url)

    assert FEED_TOKEN not in daemon_log.getvalue()
    assert '"WebSocket /ws/print-state?[token redacted]" 403' in daemon_log.getvalue()


def test_a_request_line_with_a_token_in_its_query_logs_status_and_path_without_it(
    daemon_log: io.StringIO,
) -> None:
    feed_url = f"/ws/plugin-log?plugin=camera&token={FEED_TOKEN}&tail=50"

    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d', CLIENT, "GET", feed_url, "1.1", 101,
    )

    assert FEED_TOKEN not in daemon_log.getvalue()
    assert '"GET /ws/plugin-log?plugin=camera&[token redacted]&tail=50 HTTP/1.1" 101' in (
        daemon_log.getvalue())


def test_a_traceback_that_names_the_url_logs_no_token(daemon_log: io.StringIO) -> None:
    try:
        raise RuntimeError(f"feed failed for /ws/print-state?token={FEED_TOKEN}")
    except RuntimeError:
        logging.getLogger("uvicorn.error").exception("Exception in ASGI application\n")

    assert FEED_TOKEN not in daemon_log.getvalue()
    assert "RuntimeError: feed failed for /ws/print-state?[token redacted]" in daemon_log.getvalue()
