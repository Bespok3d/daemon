"""The in-process filesystem + command actuation a fake jinni performs.

The daemon's isolated tests need the real effect (a symlink lands), but the realm boundary forbids
the daemon test suite from importing the jinni runtime, so this mirrors the jinni's actuation in
plain stdlib. The fake jinni's verb methods delegate here.
"""
import json
import shutil
import subprocess
from pathlib import Path

from protocol import ActionResult

_SYMLINK_ORIG = "symlink_orig"
_WIRING_RECORD = "wiring.json"


def _backup_path(plugin_dir: Path, destination: Path) -> Path:
    key = destination.as_posix().strip("/").replace("/", "__") or "root"
    return plugin_dir / _SYMLINK_ORIG / key


def _is_stock(path: Path) -> bool:
    return (path.is_dir() or path.is_file()) and not path.is_symlink()


def _clear(destination: Path) -> None:
    if destination.is_symlink():
        destination.unlink()
    elif destination.is_dir():
        shutil.rmtree(destination)
    elif destination.exists():
        destination.unlink()


def _reversion(destination: Path, backup: Path) -> dict[str, str]:
    if backup.exists():
        return {"action": "restore", "path": str(destination), "backup": str(backup)}
    return {"action": "unlink", "path": str(destination)}


def _merge_record(record_path: Path, reversions: list[dict[str, str]]) -> None:
    by_path: dict[str, dict[str, str]] = {}
    if record_path.exists():
        kept = json.loads(record_path.read_text())["reversions"]
        by_path = {entry["path"]: entry for entry in kept}
    for reversion in reversions:
        by_path[reversion["path"]] = reversion
    record_path.write_text(json.dumps({"reversions": list(by_path.values())}))


def _wire_one(source: Path, destination: Path, backup: Path) -> ActionResult:
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not _is_stock(destination) or backup.exists():
            _clear(destination)
        else:
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(destination), str(backup))
        destination.symlink_to(source)
    except OSError as exc:
        return ActionResult(ok=False, output=str(exc))
    return ActionResult(ok=True, output="")


def run_actions(commands: list[str]) -> list[ActionResult]:
    results = []
    for command in commands:
        done = subprocess.run(command, shell=True, capture_output=True, check=False)
        output = (done.stdout + done.stderr).decode(errors="replace").strip()
        results.append(ActionResult(ok=done.returncode == 0, output=output))
    return results


def wire(plugin_dir: str, links: list[dict]) -> list[ActionResult]:
    base = Path(plugin_dir)
    outcomes: list[ActionResult] = []
    reversions: list[dict[str, str]] = []
    for link in links:
        destination = Path(link["destination"])
        backup = _backup_path(base, destination)
        outcomes.append(_wire_one(Path(link["source"]), destination, backup))
        reversions.append(_reversion(destination, backup))
    _merge_record(base / _WIRING_RECORD, reversions)
    return outcomes


def unwire(plugin_dir: str, destinations: list[str]) -> list[ActionResult]:
    base = Path(plugin_dir)
    results: list[ActionResult] = []
    for destination in destinations:
        target, backup = Path(destination), _backup_path(base, Path(destination))
        if target.is_symlink():
            target.unlink()
        if backup.exists() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(backup), str(target))
        results.append(ActionResult(ok=True, output=""))
    return results


def write_files(plugin_dir: str, writes: list[dict]) -> list[ActionResult]:
    outcomes: list[ActionResult] = []
    reversions: list[dict[str, str]] = []
    for write in writes:
        path = Path(write["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(write["content"])
        outcomes.append(ActionResult(ok=True, output=""))
        if write.get("restore_from"):
            reversions.append({"action": "restore", "path": write["path"],
                               "backup": write["restore_from"]})
    if reversions:
        _merge_record(Path(plugin_dir) / _WIRING_RECORD, reversions)
    return outcomes


