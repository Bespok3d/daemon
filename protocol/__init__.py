"""The protocol: the one contract the daemon and the jinni both speak (ADR-0037).

The daemon orchestrates and the jinni actuates; they run as two processes and share NOTHING but this
package. It is defined here in the daemon and imported by the jinni runtime (which the daemon never
imports back). It holds the data SHAPES that cross the boundary (`contracts`), the wire format over
the 0x03-framed JSON transport (`wire`), and that transport (`frame`). No device knowledge lives
here: a service name or an action token is the jinni's vocabulary, carried through these shapes as
an opaque string the daemon relays but never authors.
"""
from . import frame
from .contracts import (
    ActionResult,
    CommandEffect,
    ControlScript,
    DeviceHealth,
    FailureSignals,
    ServiceHealth,
)
from .wire import (
    HELLO,
    PROTOCOL_VERSION,
    SUBSCRIBE_BLOCKED_ACTIONS,
    ProtocolError,
    call,
    error_bytes,
    parse_request,
    parse_result,
    request_bytes,
    result_bytes,
    stream,
)

# The socket reply timeout for the one verb that blocks while a restarted service comes back. It is
# a protocol-level policy (a generous upper bound over any device's probe budget), not a device fact
# the daemon imports from the jinni: the daemon knows the protocol's timeouts, never the jinni's
# internals.
HEALTH_CALL_TIMEOUT_S = 180.0

# The reply timeout for the actuation verb that runs the resolved device commands. A plugin start or
# a service restart can take longer than the default frame timeout; this bounds it generously so a
# hung command surfaces as a recoverable ProtocolError rather than a block.
ACTION_CALL_TIMEOUT_S = 180.0

__all__ = [
    "ACTION_CALL_TIMEOUT_S",
    "HEALTH_CALL_TIMEOUT_S",
    "HELLO",
    "PROTOCOL_VERSION",
    "SUBSCRIBE_BLOCKED_ACTIONS",
    "ActionResult",
    "CommandEffect",
    "ControlScript",
    "DeviceHealth",
    "FailureSignals",
    "ProtocolError",
    "ServiceHealth",
    "call",
    "error_bytes",
    "frame",
    "parse_request",
    "parse_result",
    "request_bytes",
    "result_bytes",
    "stream",
]
