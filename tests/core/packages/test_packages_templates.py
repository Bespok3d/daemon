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
