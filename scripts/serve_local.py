"""Run the daemon locally to inspect its Swagger UI at http://localhost:4269/docs.

DEV ONLY. Sets BESPOK3D_DEV_OPEN so the bearer middleware answers without a token (the daemon never
ships this open), points the data root at a throwaway temp dir, and injects an in-process FAKE jinni
(the daemon never imports the jinni runtime; on a printer it talks to the real jinni over a socket).
Never used on a printer. Run via scripts/serve-local.sh, which provides the Python 3.11 .venv.
"""
import os
import tempfile

os.environ.setdefault("BESPOK3D_DEV_OPEN", "1")
os.environ.setdefault("BESPOK3D_DATA_ROOT", tempfile.mkdtemp(prefix="bespok3d-dev-"))

import uvicorn  # noqa: E402  (imported after the dev env is set)

from core import jinni_client  # noqa: E402
from tests.fakes import FakeKlipperJinni  # noqa: E402

_PORT = 4269
_dev_jinni = FakeKlipperJinni()
jinni_client.dispatch.get_jinni = lambda: _dev_jinni

from api import app  # noqa: E402  (imported after the jinni seam points at the fake)


def main() -> None:
    print(f"Bespok3d daemon (dev): http://localhost:{_PORT}/docs  (no auth, fake jinni)")
    uvicorn.run(app, host="127.0.0.1", port=_PORT, log_level="info")


if __name__ == "__main__":
    main()
