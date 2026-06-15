"""Gate: the jinni process must stay lean.

The jinni is a SECOND long-lived python process the daemon parents on the printer (ADR-0037), and
the U1 ships in a 512MB variant, so its import graph must never drag in the daemon's web stack
(FastAPI / uvicorn / pydantic). It is lean today; nothing else enforces it, so this guard is the
cheap insurance against a future import silently doubling the jinni's RSS.

Faithful to the real entry: `python -m jinni <socket>` imports `jinni.service`, which pulls the
loader and the tier hierarchy. We import that chain in a clean subprocess and assert the web stack
never landed in sys.modules.
"""
import subprocess
import sys
from pathlib import Path

_DAEMON_ROOT = Path(__file__).resolve().parents[2]
_WEB_STACK = ("fastapi", "uvicorn", "pydantic", "starlette")
_PROBE = (
    "import sys, jinni.service, jinni.loader\n"
    f"print(','.join(name for name in {_WEB_STACK!r} if name in sys.modules))\n"
)


def test_jinni_entry_does_not_import_the_web_stack() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True, text=True, cwd=_DAEMON_ROOT, timeout=30, check=True,
    )
    leaked = [name for name in completed.stdout.strip().split(",") if name]
    assert not leaked, f"jinni entry imports the web stack (bloats the 2nd process): {leaked}"
