"""Klipper API-socket client: pure protocol framing + a live round-trip over a fake Unix socket."""
import json
import os
import socket
import threading

from jinni.printer_comms import klippy


def test_encode_request_is_json_terminated_by_etx() -> None:
    raw = klippy.encode_request("info", {}, request_id=7)
    assert raw.endswith(b"\x03")
    assert json.loads(raw[:-1].decode()) == {"id": 7, "method": "info", "params": {}}


def test_decode_frame_parses_first_complete_frame() -> None:
    body = json.dumps({"id": 1, "result": {"state": "ready"}}).encode() + b"\x03rest"
    assert klippy.decode_frame(body) == {"id": 1, "result": {"state": "ready"}}


def test_decode_frame_returns_empty_without_terminator() -> None:
    assert klippy.decode_frame(b'{"id": 1}') == {}


def test_state_extractors() -> None:
    query = {"result": {"status": {"print_stats": {"state": "printing"}}}}
    assert klippy.print_state_from_query(query) == "printing"
    assert klippy.klippy_state_from_info({"result": {"state": "ready"}}) == "ready"


def _serve_once(sock_path: str, response: dict) -> threading.Thread:
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_path)
    server.listen(1)

    def _run() -> None:
        conn, _addr = server.accept()
        with conn:
            conn.recv(4096)
            conn.sendall(json.dumps(response).encode() + b"\x03")
        server.close()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread


def test_query_print_state_round_trips_over_a_unix_socket() -> None:
    sock_path = f"/tmp/kuds-{os.getpid()}.sock"  # short: AF_UNIX has a ~104-byte path limit
    if os.path.exists(sock_path):
        os.unlink(sock_path)
    reply = {"id": 1, "result": {"status": {"print_stats": {"state": "printing"}}}}
    thread = _serve_once(sock_path, reply)
    try:
        assert klippy.query_print_state(sock_path) == "printing"
    finally:
        thread.join(timeout=2)
        if os.path.exists(sock_path):
            os.unlink(sock_path)


def test_query_returns_none_when_socket_absent() -> None:
    assert klippy.query_print_state(f"/tmp/kuds-missing-{os.getpid()}.sock") is None
