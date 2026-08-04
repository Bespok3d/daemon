# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The gate can build its own environment, and it notices when the one on disk is dead.

`python3.11` on PATH is usually a shim planted by uv, pyenv or asdf, and `venv` treats the directory
of the path it is handed as the new environment's home. Handed a shim directory, a relocatable
standalone build finds no stdlib there and every binary in the new venv is dead on arrival, which is
what stopped a fresh clone from ever building an environment. The half built .venv that failure
leaves behind still answers `--version`, so the gate runs code in it to tell working from dead.

Both checks are driven off the real check.sh rather than a copy of its logic, so deleting a step
from the script fails the test instead of leaving a duplicate passing here.
"""
import re
import subprocess
import sys
from pathlib import Path

CHECK_SH = Path(__file__).resolve().parent.parent / "scripts" / "check.sh"
RESOLVER_ASSIGNMENT = re.compile(
    r"^PYTHON_BIN=\"\$\(\"\$PYTHON_BIN\" -c \\?\n?\s*'(?P<expression>[^']+)'\)\"", re.MULTILINE
)
VENV_HEALTH_PROBE = re.compile(
    r"^\s*\[ -x \"\$VENV/bin/python\" \].*\n\s*\"\$VENV/bin/python\" -c '(?P<expression>[^']+)'",
    re.MULTILINE,
)


def run_probe(expression: str) -> int:
    return subprocess.run(
        [sys.executable, "-c", expression], capture_output=True, timeout=30, check=False
    ).returncode


def find_resolver(script: str) -> re.Match[str]:
    match = RESOLVER_ASSIGNMENT.search(script)
    assert match is not None, "check.sh no longer resolves PYTHON_BIN before creating the venv"
    return match


def test_the_resolver_runs_before_the_venv_is_created() -> None:
    script = CHECK_SH.read_text()
    assert find_resolver(script).start() < script.index('-m venv "$VENV"')


def test_a_shimmed_interpreter_resolves_to_the_real_one(tmp_path: Path) -> None:
    shim = tmp_path / "python3.11"
    shim.symlink_to(sys.executable)
    resolved = subprocess.run(
        [str(shim), "-c", find_resolver(CHECK_SH.read_text()).group("expression")],
        capture_output=True, text=True, timeout=30, check=True,
    ).stdout.strip()
    assert resolved != str(shim)
    assert (Path(resolved).parent.parent / "lib").is_dir()


def test_the_venv_must_run_code_to_count_as_healthy() -> None:
    script = CHECK_SH.read_text()
    probe = VENV_HEALTH_PROBE.search(script)
    assert probe is not None, "check.sh no longer runs code in .venv to decide on a rebuild"
    assert run_probe(probe.group("expression")) == 0, "the probe rejects the 3.11 suite runs on"
    wrong_version = "import sys; sys.version_info = (3, 10, 0); " + probe.group("expression")
    assert run_probe(wrong_version) != 0, "the probe accepts an interpreter that is not 3.11"
