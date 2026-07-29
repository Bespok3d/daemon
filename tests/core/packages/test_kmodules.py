# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The kernel-module install phases: generate the s05 loader script (gated on the printer's
`kernel-modules` capability) and run the immediate load. The daemon never imports the jinni runtime,
so these drive the seam with a duck-typed fake, as a real jinni answers over the socket."""
from pathlib import Path

import pytest

from core import jinni_client
from core.packages import deactivation, kmodules
from core.safety import OperationKind
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
        ["$BESPOK3D/etc/init.d/autostart/s05tun start"], ["tun"], {"BESPOK3D": "/b3d"}
    )
    assert jinni.ran == ["/b3d/etc/init.d/autostart/s05tun start"]
    assert result["ok"]
    assert result["items"][0]["output"] == "loaded"
    assert "diagnosis" not in result  # a clean load carries no failure token


class _VermagicMismatchAdapter(_KmoduleAdapter):
    def run_actions(self, commands: list[str]) -> list[ActionResult]:
        return [ActionResult(ok=False, output="Loading tun: FAILED") for _ in commands]

    def classify_module_load(self, name: str) -> str:
        return "kernel-module:vermagic-mismatch" if name == "tun" else ""


class _UnclassifiedFailureAdapter(_KmoduleAdapter):
    def run_actions(self, commands: list[str]) -> list[ActionResult]:
        return [ActionResult(ok=False, output="insmod: unknown symbol") for _ in commands]

    def classify_module_load(self, name: str) -> str:
        return ""


class _RaisingClassifyAdapter(_KmoduleAdapter):
    def run_actions(self, commands: list[str]) -> list[ActionResult]:
        return [ActionResult(ok=False, output="FAILED") for _ in commands]

    def classify_module_load(self, name: str) -> str:
        raise RuntimeError("jinni socket died")


def test_load_modules_tags_a_failed_load_with_the_jinni_diagnosis(monkeypatch: MP) -> None:
    _use(_VermagicMismatchAdapter(), monkeypatch)
    result = kmodules.load_modules(["s05tun start"], ["tun"], {})
    assert not result["ok"]
    assert result["diagnosis"] == "kernel-module:vermagic-mismatch"


def test_load_modules_omits_diagnosis_when_the_jinni_classifies_no_cause(monkeypatch: MP) -> None:
    # a load can fail for a cause the jinni does not classify (a different insmod error); then no
    # kernel token is attached and the generic install-phase reason stands
    _use(_UnclassifiedFailureAdapter(), monkeypatch)
    result = kmodules.load_modules(["s05tun start"], ["tun"], {})
    assert not result["ok"]
    assert "diagnosis" not in result


def test_load_modules_survives_a_classifier_error(monkeypatch: MP) -> None:
    # printer-never-broken: a classifier round-trip that raises (a dead jinni) must not abort the
    # load phase; it degrades to no token, so the plugin still deactivates with the generic reason
    # rather than a single install aborting before its safety net runs.
    _use(_RaisingClassifyAdapter(), monkeypatch)
    result = kmodules.load_modules(["s05tun start"], ["tun"], {})
    assert not result["ok"]
    assert "diagnosis" not in result


def test_load_failure_reason_uses_the_kmodule_token_when_present() -> None:
    # The shared reason helper (both fresh install and OTA recover deactivate through it): a failed
    # kmodule-load phase carrying the jinni's token drives the deactivation reason.
    token = "kernel-module:vermagic-mismatch"
    phase_log = [{"id": "kmodule-load", "ok": False, "diagnosis": token}]
    reason = deactivation.load_failure_reason(
        phase_log, OperationKind.INSTALL, "tun-module", "generic"
    )
    assert reason == "kernel-module:vermagic-mismatch"


def test_load_failure_reason_falls_back_without_a_kmodule_token() -> None:
    phase_log = [{"id": "templates", "ok": False, "items": []}]
    reason = deactivation.load_failure_reason(phase_log, OperationKind.INSTALL, "x", "generic")
    assert reason == "generic"
