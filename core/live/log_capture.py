# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tail a plugin's service log and pull matches (URLs by default) out of it.

A managed service's stdout/stderr is redirected by the adapter to `$BESPOK3D/var/log/<name>.log`
(see the service init template), so by default we tail that wrapper log; a plugin may override the
source with a manifest `log.path`. The websocket route streams each new match to the app, which is
how a one-time account-link URL (OctoEverywhere et al.) reaches the user without SSH.

Pure functions over text plus one async tail generator over a file. No plugin state, no network.
"""
import asyncio
import re
from collections.abc import AsyncGenerator
from pathlib import Path

URL_PATTERN = re.compile(r"https?://[^\s<>\"')]+")
DEFAULT_POLL_SECONDS = 1.0
_LOG_TAIL_BYTES = 16384


def _read_bytes(path: Path, max_bytes: int) -> str:
    try:
        return path.read_bytes()[-max_bytes:].decode(errors="replace")
    except OSError:
        return ""


def read_log_tail(path: Path, max_bytes: int = _LOG_TAIL_BYTES) -> str:
    """Tail the live log; if it is empty (a restart rotated it out), fall back to the rotated
    sibling so a match logged just before rotation is still emitted. A plugin's own log is
    bespok3d's realm, a generic file tail, not a device log (which the jinni reads)."""
    live = _read_bytes(path, max_bytes)
    if live.strip():
        return live
    for suffix in (".1", ".prev"):
        rotated = _read_bytes(path.with_name(path.name + suffix), max_bytes)
        if rotated.strip():
            return rotated
    return live


def capture_matches(text: str, pattern: re.Pattern[str]) -> list[str]:
    """Whole-match strings for every hit, deduped with first-seen order preserved. `group(0)` keeps
    a caller-supplied pattern with capture groups from collapsing to its group tuples."""
    return list(dict.fromkeys(match.group(0) for match in pattern.finditer(text)))


def capture_urls(text: str) -> list[str]:
    """The URL convenience method on top of the generic regex capture."""
    return capture_matches(text, URL_PATTERN)


def resolve_pattern(manifest: dict, name: str | None) -> re.Pattern[str]:
    """A named capture from the manifest `log.captures` map, else the built-in URL pattern."""
    captures = manifest.get("log", {}).get("captures", {})
    if name and name in captures:
        return re.compile(captures[name])
    return URL_PATTERN


def service_log_path(bespok3d_root: Path, plugin_dir: Path, manifest: dict) -> Path | None:
    """A manifest `log.path` (relative to the plugin dir) wins; otherwise the wrapper log of the
    plugin's first managed service; otherwise None (nothing to tail)."""
    declared = manifest.get("log", {}).get("path")
    if declared:
        return plugin_dir / str(declared)
    services = manifest.get("install", {}).get("service", [])
    if services:
        return bespok3d_root / "var/log" / f"{services[0]['name']}.log"
    return None


def _new_matches(text: str, pattern: re.Pattern[str], seen: set[str]) -> list[str]:
    fresh = [match for match in capture_matches(text, pattern) if match not in seen]
    seen.update(fresh)
    return fresh


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _read_from_offset(path: Path, offset: int) -> tuple[str, int]:
    """Bytes appended since `offset`. A file shorter than `offset` was rotated/truncated; re-read it
    from the start so the new content is not missed."""
    try:
        size = path.stat().st_size
    except OSError:
        return "", offset
    start = 0 if size < offset else offset
    with path.open("rb") as handle:
        handle.seek(start)
        data = handle.read()
    return data.decode(errors="replace"), start + len(data)


async def tail_and_capture(
    path: Path, pattern: re.Pattern[str], poll_seconds: float = DEFAULT_POLL_SECONDS,
) -> AsyncGenerator[str, None]:
    """Emit the matches already in the log (so a link logged before the user connected reappears),
    then poll for appended content and emit only matches not seen before."""
    seen: set[str] = set()
    snapshot = read_log_tail(path)
    offset = _file_size(path)
    for match in _new_matches(snapshot, pattern, seen):
        yield match
    while True:
        await asyncio.sleep(poll_seconds)
        chunk, offset = _read_from_offset(path, offset)
        for match in _new_matches(chunk, pattern, seen):
            yield match
