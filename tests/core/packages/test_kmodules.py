"""The kernel-module install phases: generate the s05 loader script (gated on the printer's
`kernel-modules` capability) and run the immediate load. The daemon never imports the jinni runtime,
so these drive the seam with a duck-typed fake, as a real jinni answers over the socket."""
from pathlib import Path

import pytest

from core import jinni_client
from core.packages import kmodules
from protocol import ActionResult
from tests.fakes import FakeKlipperJinni

MP = pytest.MonkeyPatch
_TUN = {
    "name": "tun", "module": "tun.ko", "device_nodes": ["/dev/net/tun c 10 200"], "autoload": True,
}


class _KmoduleAdapter(FakeKlipperJinni):
    def capability_flags(self) -> set[str]:
        return {"overlay", "managed-service", "kernel-modules"}


def _use(jinni: FakeKlipperJinni, monkeypatch: MP) -> None:
    monkeypatch.setattr(jinni_client.dispatch, "get_jinni", lambda: jinni)


def test_generate_module_loaders_writes_an_executable_s05_script(tmp_path: Path, monkeypatch: MP) -> None:  # noqa: E501
    _use(_KmoduleAdapter(), monkeypatch)
    plugin_dir = tmp_path / "tun-module"
    result = kmodules.generate_module_loaders([_TUN], plugin_dir, {})
    assert result["ok"]
    script = plugin_dir / "etc/init.d" / "s05tun"
    assert "#kmod tun tun.ko" in script.read_text()
    assert script.stat().st_mode & 0o111  # executable, so the boot runner will run it


def test_generate_module_loaders_is_refused_without_the_kernel_modules_capability(
    tmp_path: Path, monkeypatch: MP
) -> None:
    _use(FakeKlipperJinni(), monkeypatch)  # overlay + managed-service, but not kernel-modules
    result = kmodules.generate_module_loaders([_TUN], tmp_path / "tun-module", {})
    assert not result["ok"]
    assert "not supported" in result["items"][0]["label"]
    assert not (tmp_path / "tun-module" / "etc/init.d" / "s05tun").exists()


def test_generate_module_loaders_no_op_without_modules(tmp_path: Path, monkeypatch: MP) -> None:
    _use(FakeKlipperJinni(), monkeypatch)  # no modules means the capability is never even queried
    result = kmodules.generate_module_loaders([], tmp_path / "any", {})
    assert result["ok"] and result["items"] == []


class _RecordingAdapter(_KmoduleAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.ran: list[str] = []

    def run_actions(self, commands: list[str]) -> list[ActionResult]:
        self.ran.extend(commands)
        return [ActionResult(ok=True, output="loaded") for _ in commands]


def test_load_modules_runs_each_expanded_load_command(monkeypatch: MP) -> None:
    jinni = _RecordingAdapter()
    _use(jinni, monkeypatch)
    result = kmodules.load_modules(
        ["$BESPOK3D/etc/init.d/autostart/s05tun start"], {"BESPOK3D": "/b3d"}
    )
    assert jinni.ran == ["/b3d/etc/init.d/autostart/s05tun start"]
    assert result["ok"]
    assert result["items"][0]["output"] == "loaded"
