"""Moonraker API-socket client: pure framing/id-matching + a live round-trip over a fake socket."""
import json
import os
import socket
import threading

from jinni.printer_comms import moonraker


def test_encode_rpc_is_jsonrpc_terminated_by_etx() -> None:
    raw = moonraker.encode_rpc("server.info", request_id=7700)
    assert raw.endswith(b"\x03")
    assert json.loads(raw[:-1].decode()) == {"jsonrpc": "2.0", "method": "server.info", "id": 7700}


def test_decode_frames_parses_each_complete_object() -> None:
    blob = b'{"id": 1}\x03{"method": "notify"}\x03'
    assert moonraker.decode_frames(blob) == [{"id": 1}, {"method": "notify"}]


def test_result_for_id_skips_notifications_and_errors() -> None:
    frames: list[dict] = [
        {"jsonrpc": "2.0", "method": "notify_status_update", "params": []},  # id-less notification
        {"jsonrpc": "2.0", "id": 7700, "result": {"klippy_state": "ready"}},
    ]
    assert moonraker.result_for_id(frames) == {"klippy_state": "ready"}
    assert moonraker.result_for_id([{"id": 7700, "error": {"message": "x"}}]) == {}


def _serve_once(sock_path: str, frames: list[dict]) -> threading.Thread:
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_path)
    server.listen(1)

    def _run() -> None:
        conn, _addr = server.accept()
        with conn:
            conn.recv(4096)
            for frame in frames:
                conn.sendall(json.dumps(frame).encode() + b"\x03")
        server.close()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread


def test_server_info_reads_failed_components_past_a_notification() -> None:
    sock_path = f"/tmp/muds-{os.getpid()}.sock"  # short: AF_UNIX path limit
    if os.path.exists(sock_path):
        os.unlink(sock_path)
    notification = {"jsonrpc": "2.0", "method": "notify_proc_stat_update", "params": [{}]}
    info = {"klippy_state": "ready", "failed_components": ["timelapse"], "warnings": ["w"]}
    reply = {"jsonrpc": "2.0", "id": 7700, "result": info}
    thread = _serve_once(sock_path, [notification, reply])
    try:
        assert moonraker.server_info(sock_path) == info
    finally:
        thread.join(timeout=2)
        if os.path.exists(sock_path):
            os.unlink(sock_path)


def test_server_info_none_when_socket_absent() -> None:
    assert moonraker.server_info(f"/tmp/muds-missing-{os.getpid()}.sock") is None
