"""Typed shapes the jinni interface returns to the daemon.

A dataclass here crosses the jinni boundary: the daemon asks, the device jinni fills it in. Keeping
them in one leaf module lets the generic daemon AND an adapter import the shape without pulling in
the jinni tiers.
"""
from dataclasses import dataclass


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
class ServiceActionVocabulary:
    """The device-specific tokens that classify an expanded shell command as a service action.

    `display_services`: tokens (the display control script) that mark a display-service restart.
    `service_markers`: tokens (the init-script dir, the web server) that mark a deferred
    core-service action. The generic verb (restart/start/reload) lives in the classifier, not here.
    """
    display_services: tuple[str, ...] = ()
    service_markers: tuple[str, ...] = ()
