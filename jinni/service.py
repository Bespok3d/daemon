"""The jinni as a process: serve the contract over a Unix socket (ADR-0037).

The daemon spawns and parents this. It loads the device jinni, writes the jinni's startup control
scripts, starts its background tasks, then answers framed-JSON verb calls (`jinni.protocol`) on the
socket. Reviving the jinni is re-exec'ing this file, a daemonic-realm action, not a device action.

Concurrency: every current verb is a read (state, health, classification, path resolution), so
connections are served concurrently. When actuation verbs land (wiring, restart), they will
serialize through one queue while reads stay concurrent; that is the only ordering the contract
needs.
"""
import asyncio
from pathlib import Path
from typing import Any

from . import interface_extras
from .loader import get_jinni
from .printer_comms import frame
from .protocol import (
    HELLO,
    PROTOCOL_VERSION,
    SUBSCRIBE_BLOCKED_ACTIONS,
    ProtocolError,
    error_bytes,
    parse_request,
    result_bytes,
)

_READ_TIMEOUT_S = 5.0


def _handshake(jinni: Any) -> dict:
    return {"protocol_version": PROTOCOL_VERSION, "jinni_version": jinni.version()}


def _capabilities_report(jinni: Any) -> dict:
    # interface_extras is computed HERE, over the jinni object in its own process, so a custom
    # adapter cannot conceal behaviour beyond the standard interface. The anti-conceal property
    # survives the socket: this service is bespok3d's code introspecting the adapter's object.
    return {**jinni.capabilities(), "interface_extras": interface_extras(jinni)}


def _invoke(jinni: Any, verb: str, args: list[Any]) -> Any:
    if verb == HELLO:
        return _handshake(jinni)
    if verb == "capabilities_report":
        return _capabilities_report(jinni)
    return getattr(jinni, verb)(*args)


def serve_request(jinni: Any, raw: bytes) -> bytes:
    """One request frame to one reply frame: parse + version-check, dispatch the verb, encode the
    result. Any failure becomes an error frame so the daemon always gets a definite answer, never a
    dropped connection."""
    try:
        verb, args = parse_request(raw)
        return result_bytes(_invoke(jinni, verb, args))
    except ProtocolError as exc:
        return error_bytes(str(exc))
    except Exception as exc:  # noqa: BLE001 - a jinni failure is reported to the daemon, never swallowed
        return error_bytes(f"{type(exc).__name__}: {exc}")


def _requested_verb(raw: bytes) -> str | None:
    try:
        verb, _args = parse_request(raw)
        return verb
    except ProtocolError:
        return None


async def _stream_blocked_actions(writer: asyncio.StreamWriter, jinni: Any) -> None:
    """Push the blocked-action token set to the daemon whenever it changes, until the daemon closes
    the connection (its drain raises, ending the stream). One persistent subscription per client."""
    try:
        async for blocked in jinni.watch_blocked_actions():
            writer.write(result_bytes(sorted(blocked)))
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError):
        pass


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, jinni: Any) -> None:
    try:
        raw = await asyncio.wait_for(reader.readuntil(frame.ETX), _READ_TIMEOUT_S)
    except (TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
        writer.close()
        return
    if _requested_verb(raw) == SUBSCRIBE_BLOCKED_ACTIONS:
        await _stream_blocked_actions(writer, jinni)
        writer.close()
        return
    writer.write(serve_request(jinni, raw))
    await writer.drain()
    writer.close()


async def serve(socket_path: str, jinni: Any) -> asyncio.AbstractServer:
    return await asyncio.start_unix_server(
        lambda reader, writer: handle(reader, writer, jinni), path=socket_path,
    )


def _write_startup_scripts(jinni: Any) -> None:
    for script in jinni.startup_control_scripts(jinni.paths()):
        target = Path(script.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(script.content)
        target.chmod(script.mode)


async def run(socket_path: str) -> None:
    """The jinni process entry the daemon spawns: load the device jinni, do its in-process lifecycle
    (startup scripts, background tasks), then serve the contract until killed."""
    jinni = get_jinni()
    _write_startup_scripts(jinni)
    for coro in jinni.background_tasks():
        asyncio.create_task(coro)
    server = await serve(socket_path, jinni)
    async with server:
        await server.serve_forever()
