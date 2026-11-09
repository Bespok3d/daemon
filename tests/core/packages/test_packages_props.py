# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Property tests for the daemon's service dependency logic (topological recover ordering and the
dependents lookup). They run on the pure cores over in-memory manifests: a disk write per example
made each one slow enough under load to trip Hypothesis' per-example deadline, a flake with no
bearing on the logic under test.
"""
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


def plugin_manifests(graph: list[list[int]]) -> dict[str, dict]:
    """Plugin p{i} provides svc{i} and requires the services of its providers in `graph`."""
    return {
        f"p{index}": {
            "name": f"p{index}",
            "provides": [{"service": f"svc{index}"}],
            "require": [{"service": f"svc{provider}"} for provider in requires],
        }
        for index, requires in enumerate(graph)
    }


@settings(max_examples=50)
@given(acyclic_graph())
def test_order_places_every_provider_before_its_requirers(graph: list[list[int]]) -> None:
    manifests = {Path(plugin_id): manifest
                 for plugin_id, manifest in plugin_manifests(graph).items()}
    ordered = dependencies.order_by_dependency(list(manifests), manifests)
    position = {node.name: slot for slot, node in enumerate(ordered)}
    assert len(ordered) == len(graph)
    for index, requires in enumerate(graph):
        for provider in requires:
            assert position[f"p{provider}"] < position[f"p{index}"]


@settings(max_examples=50)
@given(acyclic_graph())
def test_dependents_are_exactly_the_requirers_of_a_provided_service(
    graph: list[list[int]],
) -> None:
    manifests = plugin_manifests(graph)
    for provider in range(len(graph)):
        requirers = {f"p{index}" for index, requires in enumerate(graph) if provider in requires}
        assert set(dependencies.dependents_of(manifests, f"p{provider}")) == requirers
