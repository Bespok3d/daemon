# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a package must already carry for its Python dependencies to work on the printer.

CI bakes the dependencies into the .b3 because no pip runs on the printer (ADR-0036), so a
package that arrives without them can never be made to work here: it is refused at install
rather than installed into a plugin whose code cannot import what it needs. What counts as
baked is a real artifact, never just a directory that exists: a wheels dir with no wheel feeds
pip nothing, and metadata with no package beside it links into Klipper and still imports
nothing.
"""

from pathlib import Path

from .. import python_env


def reject_conflicting_dep_files(plugin_dir: Path) -> None:
    if (plugin_dir / python_env.REQUIREMENTS_FILE).is_file() and (plugin_dir / python_env.KLIPPER_REQUIREMENTS_FILE).is_file():  # noqa: E501
        raise ValueError(
            "a plugin ships requirements.txt OR klipper_requirements.txt, not both: the first goes "
            "in the plugin's own venv, the second into the system Python for Klipper/Moonraker"
        )


def _is_importable_entry(entry: Path) -> bool:
    if entry.name in ("bin", "__pycache__") or entry.name.endswith((".dist-info", ".egg-info")):
        return False
    return entry.is_dir() or entry.suffix == ".py"


def wheels_are_baked(wheels_dir: Path) -> bool:
    """Whether the baked dir holds a wheel at all. A dir carrying only a stray file feeds pip
    nothing, so the plugin would install with none of the dependencies its code imports."""
    return any(wheels_dir.glob("*.whl"))


def importable_packages_are_baked(site_packages_dir: Path) -> bool:
    """Whether the baked dir holds something Klipper's interpreter can import. Metadata alone (a
    .dist-info with no package beside it) links into Klipper and still imports nothing."""
    if not site_packages_dir.is_dir():
        return False
    return any(_is_importable_entry(entry) for entry in site_packages_dir.iterdir())


def reject_unbaked_deps(plugin_dir: Path) -> None:
    """A shipped requirements file must come with its baked artifacts (CI bakes them; no pip runs on
    the printer). An unbaked declaration is a broken build: fail loudly here instead of provisioning
    nothing and letting the dependent component fail to import at runtime."""
    declarations = [
        (python_env.REQUIREMENTS_FILE, python_env.plugin_wheels_dir(plugin_dir), wheels_are_baked),
        (python_env.KLIPPER_REQUIREMENTS_FILE, python_env.baked_site_packages_dir(plugin_dir),
         importable_packages_are_baked),
    ]
    for declaration, baked, is_baked in declarations:
        if (plugin_dir / declaration).is_file() and not is_baked(baked):
            raise ValueError(
                f"{declaration} is present but nothing was baked into {baked.relative_to(plugin_dir)}/; "  # noqa: E501
                "rebuild so the deps ship with it (CI bakes them; the printer never pips)"
            )


def baked_top_level_names(plugin_dir: Path) -> list[str]:
    baked = python_env.baked_site_packages_dir(plugin_dir)
    if not baked.is_dir():
        return []
    return sorted(entry.name for entry in baked.iterdir() if _is_importable_entry(entry))
