# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The active-watch setting: whether the printer watches its live logs, which files it reads, and
what it does for each state its jinni recognises there.

Setting file: $BESPOK3D/etc/active-watch.json
  { "enabled": bool, "files": [path, ...], "remedies": { token: remedy } }

A missing file means the defaults. The default remedies map is the list of detectors the app shows,
so a detector this daemon ships is always listed, even under a setting saved before it existed.
"""
import logging
from typing import Literal, TypedDict, TypeGuard, get_args

from ..data_root import DATA_ROOT
from ..json_file import read_json, write_json

_log = logging.getLogger(__name__)

RemedyChoice = Literal["notify", "reboot-when-idle"]
REMEDY_CHOICES: tuple[str, ...] = get_args(RemedyChoice)

SETTINGS_PATH = DATA_ROOT / "etc/active-watch.json"
DEFAULT_REMEDIES: dict[str, RemedyChoice] = {"screen-stuck": "notify"}


class WatchSettings(TypedDict):
    enabled: bool
    files: list[str]
    remedies: dict[str, RemedyChoice]


def default_settings() -> WatchSettings:
    return {"enabled": True, "files": ["/dev/kmsg"], "remedies": dict(DEFAULT_REMEDIES)}


def _is_text_list(value: object) -> TypeGuard[list[str]]:
    return isinstance(value, list) and all(isinstance(path, str) for path in value)


def _is_remedy_map(value: object) -> TypeGuard[dict[str, RemedyChoice]]:
    if not isinstance(value, dict):
        return False
    return all(isinstance(token, str) and remedy in REMEDY_CHOICES
               for token, remedy in value.items())


def complete_settings(
    enabled: bool, files: list[str], remedies: dict[str, RemedyChoice],
) -> WatchSettings:
    """The setting with every detector this daemon ships listed, at its default when not chosen."""
    return {"enabled": enabled, "files": files, "remedies": {**DEFAULT_REMEDIES, **remedies}}


def parse_settings(stored: object) -> WatchSettings | None:
    """The setting a stored value holds, each missing field taken from the defaults, or None when
    the value is not a setting."""
    if not isinstance(stored, dict):
        return None
    merged: dict[str, object] = {**default_settings(), **stored}
    enabled, files, remedies = merged["enabled"], merged["files"], merged["remedies"]
    if not isinstance(enabled, bool) or not _is_text_list(files) or not _is_remedy_map(remedies):
        return None
    return complete_settings(enabled, files, remedies)


def load_settings() -> WatchSettings:
    """The saved setting, or the defaults when there is none. A file torn by a power cut or edited
    by hand into something else leaves the watch on its defaults rather than off; the warning says
    why the saved choice was not used."""
    if not SETTINGS_PATH.exists():
        return default_settings()
    settings = parse_settings(read_json(SETTINGS_PATH))
    if settings is None:
        _log.warning("active watch: %s is not a valid setting, using the defaults", SETTINGS_PATH)
        return default_settings()
    return settings


def save_settings(settings: WatchSettings) -> None:
    write_json(SETTINGS_PATH, settings)
