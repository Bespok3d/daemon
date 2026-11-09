# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the printer reports when it tries a web address itself.

A real web server runs on this machine for the length of the test; nothing leaves it.
"""
import socket
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from core.web_reach import http_code_at

_ANSWERS = {"/api/v1/health": 200, "/moved": 302}


class _SpoolServer(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(_ANSWERS.get(self.path, 404))
        self.send_header("Location", "/api/v1/health")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.fixture
def server_address() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SpoolServer)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def _port_nobody_listens_on() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


async def test_an_address_that_answers_reports_its_http_code(server_address: str) -> None:
    assert await http_code_at(f"{server_address}/api/v1/health") == 200


async def test_an_address_that_answers_with_an_error_still_reports_its_code(
    server_address: str,
) -> None:
    assert await http_code_at(f"{server_address}/not-spoolman") == 404


async def test_a_redirect_is_followed_to_where_it_lands(server_address: str) -> None:
    assert await http_code_at(f"{server_address}/moved") == 200


async def test_an_address_where_nothing_listens_reports_no_answer() -> None:
    assert await http_code_at(f"http://127.0.0.1:{_port_nobody_listens_on()}/") is None


@pytest.mark.parametrize("typed_address", ["spoolman.local:7912", "ftp://spoolman/", "http://[::1"])
async def test_an_address_the_printer_cannot_use_reports_no_answer(typed_address: str) -> None:
    assert await http_code_at(typed_address) is None
