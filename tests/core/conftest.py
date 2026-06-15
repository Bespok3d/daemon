"""A device-like jinni for the core tests.

The seam (`core.jinni_client`) asks the loaded jinni for the device's placement classes, restart
commands, service-command classification, and health. With no adapter installed the loader returns
the generic base jinni, which knows none of the klipper conventions, so the core tests run against
this fake klipper jinni that mirrors the U1's device facts. It is the daemon-side stand-in for "a
fully-equipped device adapter is present"; every consumer reaches it through the one seam, so the
autouse fixture only has to point the seam at the fake.
"""
import pytest

from core import jinni_client
from jinni.klipper import KlipperPrinterJinni

_RESTART_COMMANDS = {
    "klipper": "/etc/init.d/S60klipper restart",
    "moonraker": "/etc/init.d/S61moonraker restart",
    "web": "/usr/sbin/nginx -s reload",
    "lmd": "$BESPOK3D/etc/init.d/lmdctl restart",
}


class DeviceTestJinni(KlipperPrinterJinni):
    id = "test-device"

    def device_paths(self) -> dict[str, str]:
        return {key: f"/dev/null/{key}" for key in KlipperPrinterJinni.KLIPPER_PATH_KEYS}

    def restart_command(self, hook: str) -> str | None:
        return _RESTART_COMMANDS.get(hook)

    def deferred_service_markers(self) -> tuple[str, ...]:
        return ("init.d", "nginx")

    def display_service_tokens(self) -> tuple[str, ...]:
        return ("lmdctl",)


@pytest.fixture(autouse=True)
def device_jinni(monkeypatch: pytest.MonkeyPatch) -> DeviceTestJinni:
    jinni = DeviceTestJinni()
    monkeypatch.setattr(jinni_client, "get_jinni", lambda: jinni)
    return jinni
