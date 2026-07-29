# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Typed shapes the jinni interface returns to the daemon: the protocol's data contract.

A dataclass here crosses the jinni boundary: the daemon asks, the device jinni fills it in. This is
the one module the daemon and the jinni both import, so it holds only generic SHAPES, never device
vocabulary: a service name or an action token is the jinni's (see `jinni.klipper_vocab`), carried
through these shapes as an opaque string the daemon relays but never authors.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class FailureSignals:
    """What the jinni read out of its OWN service logs after a failed restart: the identifiers a
    failure names (a failing config-section header, a failing import module, a traceback file path)
    plus the formatted log tail for the user. Reading and parsing a device log is the jinni's; the
    daemon maps an identifier to the culprit plugin via its own placement records and never opens a
    device log. Empty when nothing was read."""
    sections: tuple[str, ...] = ()
    modules: tuple[str, ...] = ()
    files: tuple[str, ...] = ()
    log_tails: str = ""


@dataclass(frozen=True)
class ServiceHealth:
    """One device service's health after a risky op: whether it is ready/usable, a human detail, and
    (for a service like Moonraker whose components load dynamically) any that failed or only warned.
    A service can be reachable yet report a failed component, which plain reachability misses, so
    the safety net judges on these."""
    ready: bool
    detail: str
    failed_components: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass
class DeviceHealth:
    """The jinni's health verdict the daemon's safety net judges and acts on. The daemon asks one
    semantic question ("is the device healthy?") instead of probing each service or naming a port.

    `services` is keyed by service name, a string the jinni authors (see `jinni.klipper_vocab`); the
    safety net iterates the report and relays each key as a label, never indexing by a name it owns.
    `diagnosis` is a machine TOKEN for a NON-plugin cause when the jinni knows one (e.g. a stock
    service the printer needs is down); the safety net relays it verbatim instead of blaming a
    plugin, and the CLIENT localizes it, never the daemon. Empty means no such cause. The token
    vocabulary is the device jinni's (a device fact like the U1's MQTT broker lives behind it).
    `signals` is what the jinni read out of its logs when something failed (which section / import /
    file, plus the user-facing tail); the safety net maps those identifiers to a plugin.
    """
    services: dict[str, ServiceHealth]
    diagnosis: str = ""
    signals: FailureSignals = field(default_factory=FailureSignals)

    @property
    def healthy(self) -> bool:
        """Usable: every service ready AND none reporting a failed component."""
        return all(service.ready and not service.failed_components
                   for service in self.services.values())


@dataclass(frozen=True)
class ActionResult:
    """The outcome of one device action the daemon asked the jinni to run (a plugin start, a
    core-service restart, a stop command): whether it succeeded and the captured output, for the
    daemon's phase log. The daemon resolves and groups the actions and reports the result; running
    one (the subprocess in the device realm) is the jinni's, never the daemon's (ADR-0037)."""
    ok: bool
    output: str


@dataclass(frozen=True)
class ControlScript:
    """A control script the daemon writes into the persistent bespok3d tree at startup.

    `path` is the absolute destination (in the persistent tree, so it survives a daemon redeploy),
    `content` the rendered script text, `mode` the file mode (e.g. 0o755 for an executable).
    """
    path: str
    content: str
    mode: int


@dataclass(frozen=True)
class OomReport:
    """What the jinni read from the kernel's out-of-memory evidence (ADR-0037: reading the kernel
    counters and ring buffer is the jinni's; the daemon relays this and authors no device prose).

    `kills` is the kernel's cumulative oom_kill counter (from /proc/vmstat), 0 when the killer has
    not fired this boot; a consumer dedupes a repeat by the delta against the count it last saw.
    `token` is the jinni's machine token the app localizes ("oom-kill" when the killer fired, or ""
    when nothing was killed). `detail` is the jinni-formatted victim line for the user, "" when the
    ring buffer holds no victim line. Whether the victim was a core print service or a sacrificed
    plugin is NOT reported: the victim comm is unreliable for that (Klipper runs as `python3`), so
    it is a documented follow-up (ADR-0040). Detection for the constrained-board safety net; the
    daemon prevents no OOM from this report.
    """
    kills: int
    token: str = ""
    detail: str = ""


@dataclass(frozen=True)
class CommandEffect:
    """How one expanded start command acts on the device's services, judged by the jinni that
    produced it. The daemon reads these flags and orchestrates; it never inspects the command string
    itself (ADR-0037: the daemon does not classify commands or name services).

    `deferrable`: a service restart the daemon batches to the op's end instead of running inline.
    `restarts_services`: the core-service names (jinni vocabulary) this command restarts; the daemon
    waits for each to come back and arms the safety net around it, indexing the health report by the
    name the jinni gave, never one it authored. Empty when the command restarts no core service.
    `blocking_token`: the blocked-action token this command would trigger, or None when it touches
    no print-interrupting service. The print guard refuses the op when this token is in the jinni's
    current blocked set.
    """
    deferrable: bool
    restarts_services: tuple[str, ...]
    blocking_token: str | None
