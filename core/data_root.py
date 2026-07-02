"""The daemon's data root: the on-printer tree everything durable lives under ($BESPOK3D,
/userdata/bespok3d, survives OTA). Env-overridable so dev runs and tests point it at a throwaway
directory. Declared once here; every module that anchors a path under the root imports this."""

import os
from pathlib import Path

DATA_ROOT = Path(os.environ.get("BESPOK3D_DATA_ROOT", "/userdata/bespok3d"))
