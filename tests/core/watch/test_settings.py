# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
import json
from pathlib import Path

import pytest

from core.watch import settings


@pytest.fixture(autouse=True)
def settings_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "etc/active-watch.json"
    monkeypatch.setattr(settings, "SETTINGS_PATH", path)
    return path


def test_no_saved_setting_watches_the_kernel_log_and_notifies() -> None:
    assert settings.load_settings() == {
        "enabled": True, "files": ["/dev/kmsg"], "remedies": {"screen-stuck": "notify"},
    }


def test_a_saved_setting_is_read_back() -> None:
    chosen: settings.WatchSettings = {
        "enabled": False, "files": ["/dev/kmsg"], "remedies": {"screen-stuck": "reboot-when-idle"},
    }
    settings.save_settings(chosen)
    assert settings.load_settings() == chosen


def test_a_detector_missing_from_an_older_setting_is_listed_with_its_default(
    settings_path: Path,
) -> None:
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({"enabled": False, "remedies": {}}))
    assert settings.load_settings() == {
        "enabled": False, "files": ["/dev/kmsg"], "remedies": {"screen-stuck": "notify"},
    }


@pytest.mark.parametrize("stored_text", [
    '{"enabled": true, "remedies": {"screen-stuck": "explode"}}',
    '{"enabled": "yes"}',
    '{"files": "/dev/kmsg"}',
    '["not", "a", "setting"]',
    '{"enabled": tr',
])
def test_an_invalid_setting_leaves_the_watch_on_its_defaults(
    settings_path: Path, stored_text: str,
) -> None:
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(stored_text)
    assert settings.load_settings() == settings.default_settings()
