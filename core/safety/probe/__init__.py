"""Probe whether the printer's running services are usable.

One file per probed service plus the shared reachability primitives, so a new probe slots in beside
the existing ones. `reach` holds the low-level checks (an auth-tolerant HTTP GET, a TCP port check);
`klipper` and `moonraker` build the per-service health verdicts on top of them. Consumers import the
submodule they need (`from core.safety.probe import moonraker`).
"""
