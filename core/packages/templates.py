# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Templates: render a plugin's $VAR-expanding config templates into its own dir.

A template 'to' must stay relative and within the plugin dir (no absolute path, no parent escape),
and a template naming a value nothing supplied is never written at all.
"""

import re
from pathlib import Path

from ..results import item, phase
from .user_vars import expand

_PLACEHOLDER_RE = re.compile(r'\$([A-Z][A-Z0-9_]*)')


def unfilled_placeholders(template_body: str, vars: dict[str, str]) -> list[str]:
    """The $NAMES this template asks for that nothing in the expansion table can fill.

    Read off the TEMPLATE and not off the rendered output, so a value that happens to contain a
    dollar sign (a password, a URL) is never mistaken for a placeholder the render left behind."""
    named = {match.group(1) for match in _PLACEHOLDER_RE.finditer(template_body)}
    return sorted(name for name in named if name not in vars)


def _render_one_template(template_def: dict, plugin_dir: Path, vars: dict[str, str]) -> dict:
    template_rel = template_def["from"]
    template_to = template_def["to"]
    label = f"{template_rel} → {template_to}"
    if template_to.startswith("/") or ".." in Path(template_to).parts:
        return item(f"{label}: template 'to' must be relative and within the plugin dir", ok=False)
    template_path = plugin_dir / template_rel
    target_path = plugin_dir / template_to
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        body = template_path.read_text()
        # Nothing half-filled reaches the printer's config dir. A config file still carrying
        # `$NAME` is read by Klipper or Moonraker at startup as that literal text, which stops the
        # service; failing the phase here leaves the printer with no such file instead.
        unfilled = unfilled_placeholders(body, vars)
        if unfilled:
            return item(f"{label}: no value supplied for {', '.join(unfilled)}", ok=False)
        target_path.write_text(expand(body, vars))
    except Exception as exc:
        return item(f"{label}: {exc}", ok=False)
    return item(label, ok=True)


def render_templates(templates: list[dict], plugin_dir: Path, vars: dict[str, str]) -> dict:
    items = [_render_one_template(template_def, plugin_dir, vars) for template_def in templates]
    return phase("templates", "Templates", items)
