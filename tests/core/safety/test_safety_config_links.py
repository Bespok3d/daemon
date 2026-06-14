"""Dead-symlink self-heal tests for the bespok3d include dirs."""
from pathlib import Path

from core.safety import config_links


def test_prune_dead_config_links_removes_only_broken_links(tmp_path: Path) -> None:
    config_dir = tmp_path / "moonraker"
    config_dir.mkdir()
    real_target = tmp_path / "real.cfg"
    real_target.write_text("[spoolman]\n")
    live_link = config_dir / "live.cfg"
    live_link.symlink_to(real_target)
    dead_link = config_dir / "gone.cfg"
    dead_link.symlink_to(tmp_path / "missing.cfg")

    removed = config_links.prune_dead_config_links([config_dir])

    assert removed == [str(dead_link)]
    assert not dead_link.is_symlink()
    assert live_link.is_symlink()
