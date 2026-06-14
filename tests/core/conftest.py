"""A device-like jinni for the core tests.

The intent translation and several package paths ask `get_jinni()` for the device's placement
classes, restart commands, and service-action vocabulary (ADR-0029). With no adapter installed the
loader returns the generic base jinni, which knows none of the klipper conventions, so the core
tests run against this fake klipper jinni that mirrors the U1's device facts. It is the daemon-side
stand-in for "a fully-equipped device adapter is present"; it grows as Part 1 adds device methods.
"""
import pytest

from core import intent
from core.packages import print_guard, start_commands, uninstaller
from core.safety import config_links
from jinni.contracts import ServiceActionVocabulary
from jinni.klipper import KlipperPrinterJinni

_RESTART_COMMANDS = {
    "klipper": "/etc/init.d/S60klipper restart",
    "moonraker": "/etc/init.d/S61moonraker restart",
    "web": "/usr/sbin/nginx -s reload",
    "lmd": "$BESPOK3D/etc/init.d/lmdctl restart",
}

# The modules that ask get_jinni() for a device fact; the autouse fixture points each at the fake.
_JINNI_CONSUMERS = (intent, uninstaller, config_links, print_guard, start_commands)


class DeviceTestJinni(KlipperPrinterJinni):
    id = "test-device"

    def device_paths(self) -> dict[str, str]:
        return {key: f"/dev/null/{key}" for key in KlipperPrinterJinni.KLIPPER_PATH_KEYS}

    def restart_command(self, hook: str) -> str | None:
        return _RESTART_COMMANDS.get(hook)

    def service_action_vocabulary(self) -> ServiceActionVocabulary:
        return ServiceActionVocabulary(
            display_services=("lmdctl",), service_markers=("init.d", "nginx")
        )


@pytest.fixture(autouse=True)
def device_jinni(monkeypatch: pytest.MonkeyPatch) -> DeviceTestJinni:
    jinni = DeviceTestJinni()
    for module in _JINNI_CONSUMERS:
        monkeypatch.setattr(module, "get_jinni", lambda: jinni)
    return jinni
