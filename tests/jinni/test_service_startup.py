"""The jinni process writes the device's startup control scripts before serving (ADR-0037).

The child does its own in-process lifecycle: on `run`, before it serves the contract, it writes the
control scripts the jinni declares into the persistent bespok3d tree (a display control script on
the U1, nothing on a generic box). These cover `service._write_startup_scripts` directly.
"""
from pathlib import Path

from jinni import service
from jinni.base import Jinni
from jinni.contracts import ControlScript


class _BareJinni(Jinni):
    def __init__(self, root: str) -> None:
        self._root = root

    def data_root(self) -> str:
        return self._root


class _ControlScriptJinni(_BareJinni):
    def startup_control_scripts(self, paths: dict[str, str]) -> list[ControlScript]:
        target = f"{paths['BESPOK3D']}/etc/init.d/lmdctl"
        return [ControlScript(path=target, content="#!/bin/sh\n# lmdctl\n", mode=0o755)]


def test_write_startup_scripts_writes_the_declared_scripts(tmp_path: Path) -> None:
    service._write_startup_scripts(_ControlScriptJinni(str(tmp_path)))
    target = tmp_path / "etc" / "init.d" / "lmdctl"
    assert target.read_text() == "#!/bin/sh\n# lmdctl\n"
    assert target.stat().st_mode & 0o755 == 0o755


def test_a_jinni_with_no_startup_scripts_writes_nothing(tmp_path: Path) -> None:
    service._write_startup_scripts(_BareJinni(str(tmp_path)))
    assert not (tmp_path / "etc" / "init.d").exists()
