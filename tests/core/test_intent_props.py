import pytest
from hypothesis import given
from hypothesis import strategies as st

from core import intent
from jinni.realization import _BESPOK3D_PLACEMENTS, _KLIPPER_PLACEMENTS

_PLACEMENT_CLASSES = sorted({*_BESPOK3D_PLACEMENTS, *_KLIPPER_PLACEMENTS})
# The restart hooks the device jinni (tests/core/conftest.py DeviceTestJinni) resolves to a command.
_RESTART_HOOKS = ("klipper", "moonraker", "web", "lmd")

name_st = st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=8)
placement_st = st.fixed_dictionaries({
    "class": st.sampled_from(_PLACEMENT_CLASSES),
    "src": name_st.map(lambda stem: f"files/{stem}.cfg"),
    "render": st.booleans(),
})
service_st = st.fixed_dictionaries({"name": name_st, "autostart": st.booleans()})


@given(st.lists(placement_st, max_size=6))
def test_each_placement_yields_one_symlink_and_a_template_per_render(
    placements: list[dict],
) -> None:
    result = intent.normalize_install({"place": placements})
    assert len(result["symlinks"]) == len(placements)
    assert len(result["templates"]) == sum(
        1 for placement in placements if placement["render"]
    )


@given(st.lists(service_st, max_size=6))
def test_each_service_wires_a_symlink_a_stop_and_an_optional_start(services: list[dict]) -> None:
    result = intent.normalize_install({"service": services})
    assert len(result["symlinks"]) == len(services)
    assert len(result["stops"]) == len(services)
    assert len(result["start"]) == sum(1 for service in services if service["autostart"])


@given(st.lists(st.sampled_from(_RESTART_HOOKS), max_size=4))
def test_each_known_restart_hook_yields_one_command(hooks: list[str]) -> None:
    result = intent.normalize_install({"restart": hooks})
    assert len(result["start"]) == len(hooks)


@given(st.lists(name_st, max_size=6))
def test_each_data_name_yields_one_dir(names: list[str]) -> None:
    result = intent.normalize_install({"data": names})
    assert len(result["dirs"]) == len(names)


def test_unknown_restart_hook_raises() -> None:
    with pytest.raises(ValueError):
        intent.normalize_install({"restart": ["definitely-not-a-hook"]})
