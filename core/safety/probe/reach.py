"""Low-level reachability checks shared by the per-service probes.

`service_get` answers "is this localhost service answering HTTP" (an auth-required response still
counts as up); `port_listening` answers "is this TCP port open". The per-service probes build their
richer health verdicts on these two primitives.
"""
import socket
import urllib.error
import urllib.request

MQTT_PORT = 1883

# Moonraker / Klipper return these when `[authorization] force_logins` is on (the moonraker-auth
# plugin): the service IS up and answering, it just demands a login. That is a healthy, expected
# response, NOT a failure, so the probes must not read it as "down" (which auto-deactivated the
# plugin that set it).
_AUTH_REQUIRED_CODES = (401, 403)


def service_get(url: str, timeout: int = 3) -> tuple[bool, str]:
    """GET a localhost service URL. Returns (up, body). An auth-required response still means the
    service is up; a connection error (refused / timeout) means it is not yet up."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return True, resp.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code in _AUTH_REQUIRED_CODES:
            return True, f"auth required (HTTP {exc.code}); service is up"
        return False, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 - connection refused / timeout means not-yet-up
        return False, str(exc)


def port_listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.3)
        return connection.connect_ex(("127.0.0.1", port)) == 0
