"""The generic-daemon boundary guard: core/ reaches the jinni only through the seam.

Driven end-to-end over a synthetic core/ tree so it exercises the real script: detection, the seam
exemption, and the exit code the gate keys on.
"""
import subprocess
import sys
from pathlib import Path

_GUARD = Path(__file__).resolve().parent.parent / "scripts" / "generic_daemon_guard.py"


def _run_guard(workspace: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_GUARD)],
        cwd=workspace, capture_output=True, text=True, timeout=30, check=False,
    )


def _write(workspace: Path, relative: str, source: str) -> None:
    target = workspace / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source)


def test_a_device_import_in_core_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "core/installer.py", "from jinni.base import Jinni\n")
    result = _run_guard(tmp_path)
    assert result.returncode == 1
    assert "core/installer.py" in result.stdout


def test_an_import_statement_reaching_the_jinni_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "core/installer.py", "import jinni.loader\n")
    result = _run_guard(tmp_path)
    assert result.returncode == 1


def test_the_shared_contract_shapes_are_allowed(tmp_path: Path) -> None:
    _write(tmp_path, "core/decision.py", "from jinni.contracts import MoonrakerInfo\n")
    _write(tmp_path, "core/installer.py", "from core.intent import normalize_install\n")
    assert _run_guard(tmp_path).returncode == 0


def test_the_seam_module_may_reach_the_jinni(tmp_path: Path) -> None:
    _write(tmp_path, "core/jinni_client.py", "from jinni.loader import get_jinni\n")
    assert _run_guard(tmp_path).returncode == 0


def test_the_seam_package_may_reach_the_jinni(tmp_path: Path) -> None:
    source = "from jinni.klipper import KlipperPrinterJinni\n"
    _write(tmp_path, "core/jinni_client/health.py", source)
    assert _run_guard(tmp_path).returncode == 0
