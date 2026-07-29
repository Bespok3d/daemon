# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The generic-daemon boundary guard: no core/ code imports the jinni runtime (only the protocol
crosses), and the protocol contract carries no device vocabulary.

Driven end-to-end over a synthetic core/ tree so it exercises the real script: detection, the
protocol exemption, the contract-purity check, and the exit code the gate keys on.
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


def test_importing_the_protocol_is_allowed(tmp_path: Path) -> None:
    _write(tmp_path, "core/decision.py", "from protocol import DeviceHealth\n")
    _write(tmp_path, "core/installer.py", "from core.intent import normalize_install\n")
    assert _run_guard(tmp_path).returncode == 0


def test_even_the_seam_may_not_import_the_jinni_runtime(tmp_path: Path) -> None:
    # Only the protocol crosses: the seam talks to the jinni over the socket and injects its
    # in-process jinni for tests; it never imports the jinni runtime either.
    _write(tmp_path, "core/jinni_client/__init__.py", "from jinni.loader import get_jinni\n")
    assert _run_guard(tmp_path).returncode == 1


def test_a_device_string_constant_in_the_protocol_contract_is_flagged(tmp_path: Path) -> None:
    _write(tmp_path, "protocol/contracts.py", 'KLIPPER_SERVICE = "klipper"\n')
    result = _run_guard(tmp_path)
    assert result.returncode == 1
    assert "KLIPPER_SERVICE" in result.stdout


def test_dataclass_shapes_in_the_protocol_contract_are_allowed(tmp_path: Path) -> None:
    source = (
        "from dataclasses import dataclass\n\n"
        "@dataclass\nclass DeviceHealth:\n    diagnosis: str = \"\"\n"
    )
    _write(tmp_path, "protocol/contracts.py", source)
    assert _run_guard(tmp_path).returncode == 0
