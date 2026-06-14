"""Read service log tails and pull failure signals out of them.

Pure functions over text and files: no plugin state, no network. Used by the attribution and chain
layers to turn a Klipper/Moonraker log into "which section / module / file failed".
"""
import re
from pathlib import Path

_CFG_SECTION_HEADER_RE = re.compile(r"^\s*\[([^\]]+)\]", re.MULTILINE)
_CONFIG_SECTION_RE = re.compile(r"(?:[Ss]ection|config object)\s+'([^']+)'")
_NO_MODULE_RE = re.compile(r"No module named '([^']+)'")
_IMPORT_ERROR_RE = re.compile(r"(?:ImportError|ModuleNotFoundError):[^\n]*?'([A-Za-z0-9_.]+)'")
_TRACEBACK_FILE_RE = re.compile(r'File "(/[^"]+\.py)"')

LOG_TAIL_BYTES = 16384

# vars keys for the two service logs, in the order the safety net reads them.
SERVICE_LOGS = (("Klipper", "KLIPPER_LOG"), ("Moonraker", "MOONRAKER_LOG"))


def _read_bytes(path: Path, max_bytes: int) -> str:
    try:
        return path.read_bytes()[-max_bytes:].decode(errors="replace")
    except OSError:
        return ""


def read_log_tail(path: Path, max_bytes: int = LOG_TAIL_BYTES) -> str:
    """Tail the live log; if it is empty (a restart rotated it out from under us), fall back to the
    sibling rotated file so the crash that triggered the rotation is still recovered."""
    live = _read_bytes(path, max_bytes)
    if live.strip():
        return live
    for suffix in (".1", ".prev"):
        rotated = _read_bytes(path.with_name(path.name + suffix), max_bytes)
        if rotated.strip():
            return rotated
    return live


def cfg_sections(cfg_path: Path) -> list[str]:
    try:
        text = cfg_path.read_text(errors="replace")
    except OSError:
        return []
    return [header.strip() for header in _CFG_SECTION_HEADER_RE.findall(text)]


def failing_config_section(log_text: str) -> str | None:
    match = _CONFIG_SECTION_RE.search(log_text)
    return match.group(1).strip() if match else None


def failing_import_module(log_text: str) -> str | None:
    for pattern in (_NO_MODULE_RE, _IMPORT_ERROR_RE):
        match = pattern.search(log_text)
        if match:
            return match.group(1).split(".")[0]
    return None


def failing_file(log_text: str) -> str | None:
    matches = _TRACEBACK_FILE_RE.findall(log_text)
    return matches[-1] if matches else None


def format_tails(klipper_log: str, moonraker_log: str) -> str:
    """Format already-captured Klipper/Moonraker tails into the diagnostic block. Surfaces the
    FIRST-failure traceback (captured before any auto-recovery restart); a later successful restart
    would otherwise overwrite the live log, leaving a useless clean tail in the report."""
    sections = []
    for label, tail in (("Klipper", klipper_log), ("Moonraker", moonraker_log)):
        clean = tail.strip()
        if clean:
            sections.append(f"--- {label} log ---\n{clean}")
    return "\n\n".join(sections)


def service_log_tails(vars: dict[str, str]) -> str:
    """The live tail of the Klipper and Moonraker logs, so a failed restart hands the user (or the
    person they report to) the actual traceback rather than just 'did not come back up'."""
    sections = []
    for label, log_var in SERVICE_LOGS:
        log_path = vars.get(log_var)
        if not log_path:
            continue
        tail = read_log_tail(Path(log_path)).strip()
        if tail:
            sections.append(f"--- {label} log ({log_path}) ---\n{tail}")
    return "\n\n".join(sections)
