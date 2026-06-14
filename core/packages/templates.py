"""Templates: render a plugin's $VAR-expanding config templates into its own dir.

A template 'to' must stay relative and within the plugin dir (no absolute path, no parent escape).
"""

from pathlib import Path

from ..results import item, phase
from .user_vars import expand


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
        target_path.write_text(expand(body, vars))
    except Exception as exc:
        return item(f"{label}: {exc}", ok=False)
    return item(label, ok=True)


def render_templates(templates: list[dict], plugin_dir: Path, vars: dict[str, str]) -> dict:
    items = [_render_one_template(template_def, plugin_dir, vars) for template_def in templates]
    return phase("templates", "Templates", items)
