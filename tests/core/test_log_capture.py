import asyncio
import re
from pathlib import Path

from core import log_capture

_OE_LINE = "Companion ready. Link this printer: https://octoeverywhere.com/getstarted?code=ABC123\n"


def test_capture_matches_dedupes_preserving_order() -> None:
    text = "see https://b.example then https://a.example then https://b.example again"
    assert log_capture.capture_matches(text, log_capture.URL_PATTERN) == [
        "https://b.example",
        "https://a.example",
    ]


def test_capture_urls_extracts_link_and_ignores_prose() -> None:
    assert log_capture.capture_urls(_OE_LINE) == [
        "https://octoeverywhere.com/getstarted?code=ABC123"
    ]
    assert log_capture.capture_urls("no module named moonraker_octoeverywhere") == []


def test_capture_matches_keeps_whole_match_for_grouped_pattern() -> None:
    pattern = re.compile(r"code=(\w+)")
    assert log_capture.capture_matches(_OE_LINE, pattern) == ["code=ABC123"]


def test_resolve_pattern_defaults_to_url() -> None:
    assert log_capture.resolve_pattern({}, None) is log_capture.URL_PATTERN
    empty: dict[str, object] = {"log": {"captures": {}}}
    assert log_capture.resolve_pattern(empty, "missing") is log_capture.URL_PATTERN


def test_resolve_pattern_uses_named_capture() -> None:
    manifest = {"log": {"captures": {"token": r"tok_[a-z0-9]+"}}}
    pattern = log_capture.resolve_pattern(manifest, "token")
    assert pattern.findall("here is tok_abc99 done") == ["tok_abc99"]


def test_service_log_path_override_wins(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins" / "octoeverywhere"
    manifest = {"name": "octoeverywhere", "log": {"path": "var/octoeverywhere/logs/oe.log"}}
    assert log_capture.service_log_path(tmp_path, plugin_dir, manifest) == (
        plugin_dir / "var/octoeverywhere/logs/oe.log"
    )


def test_service_log_path_defaults_to_service_wrapper_log(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugins" / "octoeverywhere"
    manifest = {"name": "octoeverywhere", "install": {"service": [{"name": "octoeverywhere"}]}}
    assert log_capture.service_log_path(tmp_path, plugin_dir, manifest) == (
        tmp_path / "var/log" / "octoeverywhere.log"
    )


def test_service_log_path_none_without_service_or_override(tmp_path: Path) -> None:
    manifest = {"name": "cpu-temp", "install": {}}
    assert log_capture.service_log_path(tmp_path, tmp_path / "p", manifest) is None


async def test_tail_and_capture_snapshot_then_new_only(tmp_path: Path) -> None:
    log = tmp_path / "svc.log"
    log.write_text("boot https://oe.example/one\n")
    feed = log_capture.tail_and_capture(log, log_capture.URL_PATTERN, poll_seconds=0.01)
    assert await asyncio.wait_for(anext(feed), timeout=2) == "https://oe.example/one"
    with log.open("a") as handle:
        handle.write("again https://oe.example/one\nnew https://oe.example/two\n")
    assert await asyncio.wait_for(anext(feed), timeout=2) == "https://oe.example/two"
    await feed.aclose()


async def test_tail_and_capture_rereads_after_truncation(tmp_path: Path) -> None:
    log = tmp_path / "svc.log"
    log.write_text("first https://oe.example/one\n")
    feed = log_capture.tail_and_capture(log, log_capture.URL_PATTERN, poll_seconds=0.01)
    assert await asyncio.wait_for(anext(feed), timeout=2) == "https://oe.example/one"
    log.write_text("https://oe.example/three\n")
    assert await asyncio.wait_for(anext(feed), timeout=2) == "https://oe.example/three"
    await feed.aclose()
