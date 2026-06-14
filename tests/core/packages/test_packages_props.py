"""Property tests for the daemon's service dependency logic (topological recover ordering and the
installed-dependents lookup). These are filesystem-backed (the functions read each plugin's
manifest.json), so each example writes a small generated service graph into a fresh temp dir.
"""
import json
import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from core.packages import dependencies


@st.composite
def acyclic_graph(draw: st.DrawFn) -> list[list[int]]:
    """Plugin i provides svc{i} and may require services of earlier plugins only (so it is acyclic).

    Returns, per plugin index, the list of provider indices it requires.
    """
    count = draw(st.integers(min_value=1, max_value=6))
    requirements: list[list[int]] = []
    for index in range(count):
        providers = st.integers(min_value=0, max_value=index - 1)
        choices = st.lists(providers, unique=True, max_size=index)
        requirements.append(sorted(draw(choices)) if index else [])
    return requirements


def write_plugin(root: Path, index: int, requires: list[int]) -> Path:
    plugin_dir = root / f"p{index}"
    plugin_dir.mkdir()
    manifest = {
        "name": f"p{index}",
        "version": "1.0.0",
        "provides": [{"service": f"svc{index}"}],
        "require": [{"service": f"svc{provider}"} for provider in requires],
    }
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest))
    return plugin_dir


@settings(max_examples=50)
@given(acyclic_graph())
def test_topo_sort_places_every_provider_before_its_requirers(graph: list[list[int]]) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dirs = [write_plugin(root, index, requires) for index, requires in enumerate(graph)]
        ordered = dependencies.topo_sort(dirs)
        position = {entry.name: slot for slot, entry in enumerate(ordered)}
        assert len(ordered) == len(dirs)
        for index, requires in enumerate(graph):
            for provider in requires:
                assert position[f"p{provider}"] < position[f"p{index}"]


@settings(max_examples=50)
@given(acyclic_graph())
def test_installed_dependents_lists_every_requirer_of_a_provided_service(
    graph: list[list[int]],
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for index, requires in enumerate(graph):
            write_plugin(root, index, requires)
        for index, requires in enumerate(graph):
            for provider in requires:
                assert f"p{index}" in dependencies.installed_dependents(root, f"p{provider}")
