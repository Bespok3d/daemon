# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Template rendering (the $VAR-expanding config-template writer) has a canonical home in
core.packages.templates. These guard the path-escape rejection a template 'to' must enforce."""
from pathlib import Path

from core.packages import templates


def test_render_one_template_expands_vars(tmp_path: Path) -> None:
    (tmp_path / "in.tmpl").write_text("server=$HOST\n")
    item = templates._render_one_template(
        {"from": "in.tmpl", "to": "out.cfg"}, tmp_path, {"HOST": "printer"}
    )
    assert item["ok"] is True
    assert (tmp_path / "out.cfg").read_text() == "server=printer\n"


def test_render_one_template_rejects_absolute_destination(tmp_path: Path) -> None:
    item = templates._render_one_template(
        {"from": "in.tmpl", "to": "/etc/passwd"}, tmp_path, {}
    )
    assert item["ok"] is False


def test_render_one_template_rejects_parent_escape(tmp_path: Path) -> None:
    item = templates._render_one_template(
        {"from": "in.tmpl", "to": "../escape.cfg"}, tmp_path, {}
    )
    assert item["ok"] is False


def test_render_templates_returns_phase_with_items(tmp_path: Path) -> None:
    (tmp_path / "in.tmpl").write_text("x=$V\n")
    defs = [{"from": "in.tmpl", "to": "out.cfg"}]
    phase = templates.render_templates(defs, tmp_path, {"V": "1"})
    assert phase["id"] == "templates"
    assert len(phase["items"]) == 1


def test_render_one_template_refuses_a_value_nothing_supplied(tmp_path: Path) -> None:
    """A config file still holding `$NAME` is read by Klipper at startup as that literal text, which
    stops the service. Nothing half-filled is written at all."""
    (tmp_path / "in.tmpl").write_text("logging: $SPOOLMAN_LOGGING\n")

    item = templates._render_one_template({"from": "in.tmpl", "to": "out.cfg"}, tmp_path, {})

    assert item["ok"] is False
    assert "SPOOLMAN_LOGGING" in item["label"]
    assert not (tmp_path / "out.cfg").exists()


def test_render_one_template_allows_a_value_that_itself_contains_a_dollar(tmp_path: Path) -> None:
    """The check reads the TEMPLATE, so a password or a URL carrying a dollar sign is never mistaken
    for a placeholder the render left behind."""
    (tmp_path / "in.tmpl").write_text("password=$SECRET\n")

    item = templates._render_one_template(
        {"from": "in.tmpl", "to": "out.cfg"}, tmp_path, {"SECRET": "p$SSWORD"}
    )

    assert item["ok"] is True
    assert (tmp_path / "out.cfg").read_text() == "password=p$SSWORD\n"


def test_unfilled_placeholders_lists_only_the_names_nothing_can_fill() -> None:
    body = "server=$HOST\nmode=$MODE\nport=$HOST\n"

    assert templates.unfilled_placeholders(body, {"HOST": "printer"}) == ["MODE"]
