"""The chain of fixers: each recognises ONE class of failure and names the culprit (or that no
plugin is at fault). They are pure - they read the gathered evidence and the operation context and
return a `Decision` or None. The daemon walks the chain and acts on the first hit; the catch-all at
the end guarantees the user is never left without an explanation.

If a real failure ever reaches the catch-all (`escaped=True`), that is the signal that we need a new
specific fixer.
"""

import re
from collections.abc import Callable

from protocol import ServiceHealth

from .context import OperationContext
from .decision import Decision, FailureEvidence
from .kernel_fixer import kernel_module_failure

Fixer = Callable[[FailureEvidence, OperationContext, list[str]], Decision | None]

_BRACKET_SECTION_RE = re.compile(r"\[([^\]]+)\]")
_COMPONENT_FAILURE = "component-failure"


def _component_section_owner(component: str, evidence: FailureEvidence) -> str | None:
    """A failed component name (e.g. 'notifier') is owned by the plugin that placed a config section
    whose first word is that name (e.g. '[notifier phone]')."""
    for section, plugin_id in evidence.index.by_section.items():
        if section.split()[:1] == [component]:
            return plugin_id
    return None


def _failed_component_culprit(service: ServiceHealth, evidence: FailureEvidence, already: list[str]) -> tuple[str, str] | None:  # noqa: E501
    for component in service.failed_components:
        plugin_id = _component_section_owner(component, evidence)
        if plugin_id and plugin_id not in already:
            return plugin_id, component
    return None


def _warned_section_culprit(service: ServiceHealth, evidence: FailureEvidence, already: list[str]) -> tuple[str, str] | None:  # noqa: E501
    sections = (s for warning in service.warnings for s in _BRACKET_SECTION_RE.findall(warning))
    for section in sections:
        plugin_id = evidence.index.plugin_for_section(section)
        if plugin_id and plugin_id not in already:
            return plugin_id, section
    return None


def component_failure(
    evidence: FailureEvidence,
    _ctx: OperationContext,
    already: list[str],
) -> Decision | None:
    """A service is reachable but a component failed to import (the apprise/notifier case). Blame
    the plugin that activated the component via its config section. The daemon reads the failed
    components out of the jinni's per-service report without naming any service."""
    for service in evidence.health.services.values():
        failed = _failed_component_culprit(service, evidence, already)
        if failed:
            plugin_id, component = failed
            return Decision(plugin_id, f"component '{component}' failed to load", _COMPONENT_FAILURE)  # noqa: E501
        warned = _warned_section_culprit(service, evidence, already)
        if warned:
            plugin_id, section = warned
            return Decision(plugin_id, f"config section [{section}] failed to load", _COMPONENT_FAILURE)  # noqa: E501
    return None


def placement_failure(
    evidence: FailureEvidence,
    _ctx: OperationContext,
    already: list[str],
) -> Decision | None:
    """A failing config section, a missing import, or a traceback in a placed file: the jinni read
    the identifier out of the device log, the daemon names the plugin that placed it."""
    from .attribution import attribute

    culprit, signal = attribute(evidence.health.signals, evidence.index)
    if culprit and culprit not in already:
        return Decision(culprit, signal, "placement-failure")
    return None


def device_infrastructure(
    evidence: FailureEvidence,
    _ctx: OperationContext,
    _already: list[str],
) -> Decision | None:
    """The jinni diagnosed a non-plugin cause and emits a TOKEN for it (e.g. the U1's stock MQTT
    broker is down): relay the token verbatim and deactivate nothing. The token is the jinni's; the
    daemon never turns it into a sentence, the app localizes it."""
    if evidence.health.diagnosis:
        return Decision(None, evidence.health.diagnosis, "device-infrastructure")
    return None


def last_resort_target(
    evidence: FailureEvidence,
    ctx: OperationContext,
    already: list[str],
) -> Decision | None:
    """Nothing was attributable, but the printer is broken and we were operating on one plugin.
    Deactivate that plugin as the most likely cause - printer preservation comes first."""
    if ctx.plugin_id and ctx.plugin_id not in already:
        return Decision(
            ctx.plugin_id,
            f"deactivated {ctx.plugin_id}, the plugin being {ctx.human_action()}, "
            "as the most likely cause",
            "last-resort",
        )
    return None


def catch_all(
    _evidence: FailureEvidence,
    ctx: OperationContext,
    _already: list[str],
) -> Decision | None:
    """The floor: never leave the user hanging. We could not auto-fix it; gather what we know and
    tell the user what to try."""
    suspect = ctx.plugin_id or "a recently changed plugin"
    return Decision(
        None,
        f"During {ctx.human_action()} an unforeseen issue arose and we could not auto-fix it. "
        f"Try uninstalling {suspect} and your printer should print again. Please share this with "
        "the plugin developer, and the Bespok3d Org, and check whether an updated version "
        "has been released.",
        "catch-all",
        escaped=True,
    )


def default_chain() -> list[Fixer]:
    return [
        component_failure,
        placement_failure,
        device_infrastructure,
        kernel_module_failure,
        last_resort_target,
        catch_all,
    ]
