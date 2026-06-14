"""Run one shell command and report it as a result item. Leaf module shared by the package executor
(start commands) and the safety net (restart batch) so both run and capture identically.
"""
import os
import subprocess

from .results import MAX_OUTPUT_BYTES, item


def start_env() -> dict[str, str]:
    return {**os.environ, "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"}


def run_one_command(expanded: str, env: dict[str, str]) -> dict:
    result = subprocess.run(expanded, shell=True, capture_output=True, check=False, env=env)
    raw = (result.stdout + result.stderr).decode(errors="replace")
    output = raw[:MAX_OUTPUT_BYTES] + ("…" if len(raw) > MAX_OUTPUT_BYTES else "")
    return item(expanded, ok=result.returncode == 0, output=output.strip())
