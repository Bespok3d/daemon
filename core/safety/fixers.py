"""The chain of fixers: each recognises ONE class of failure and names the culprit (or, for the
broker, that no plugin is at fault). They are pure - they read the gathered evidence and the
operation context and return a `Decision` or None. The daemon walks the chain and acts on the first
hit; the catch-all at the end guarantees the user is never left without an explanation.

If a real failure ever reaches the catch-all (`escaped=True`), that is the signal that we need a new
specific fixer.
"""

import re

from .context import OperationContext
from .decision import Decision, FailureEvidence

_BRACKET_SECTION_RE = re.compile(r"\[([^\]]+)\]")


def _component_section_owner(component: str, evidence: FailureEvidence) -> str | None:
    """A Moonraker component name (e.g. 'notifier') is owned by the plugin that placed a config
    section whose first word is that name (e.g. '[notifier phone]')."""
    for section, plugin_id in evidence.index.by_section.items():
        if section.split()[:1] == [component]:
            return plugin_id
    return None


def moonraker_component_failure(
    evidence: FailureEvidence,
    _ctx: OperationContext,
    already: list[str],
) -> Decision | None:
    """Moonraker is reachable but a component failed to import (the apprise/notifier case). Blame
    the plugin that activated the component via its config section."""
    info = evidence.moonraker
    for component in info.failed_components:
        plugin_id = _component_section_owner(component, evidence)
        if plugin_id and plugin_id not in already:
            return Decision(
                plugin_id,
                f"Moonraker component '{component}' failed to load",
                "moonraker-component",
            )
    for warning in info.warnings:
        for section in _BRACKET_SECTION_RE.findall(warning):
            plugin_id = evidence.index.plugin_for_section(section)
            if plugin_id and plugin_id not in already:
                return Decision(
                    plugin_id,
                    f"Moonraker config section [{section}] failed to load",
                    "moonraker-component",
                )
    return None


def _attribute_logs(evidence: FailureEvidence) -> tuple[str | None, str]:
    from .attribution import attribute_failure

    for log_text in (evidence.klipper_log, evidence.moonraker_log):
        culprit, signal = attribute_failure(log_text, evidence.index)
        if culprit:
            return culprit, signal
    return None, ""


def klipper_import_failure(
    evidence: FailureEvidence,
    _ctx: OperationContext,
    already: list[str],
) -> Decision | None:
    """A failing Klipper config section, a missing import, or a traceback in a placed file."""
    culprit, signal = _attribute_logs(evidence)
    if culprit and culprit not in already:
        return Decision(culprit, signal, "klipper-import")
    return None


def broker_down(
    evidence: FailureEvidence,
    _ctx: OperationContext,
    _already: list[str],
) -> Decision | None:
    """Klipper is down and the stock MQTT broker is too: not a plugin's fault, so say so honestly
    and deactivate nothing."""
    if not evidence.klipper_reachable and not evidence.mqtt_up:
        return Decision(
            None,
            "Klipper did not come back and the MQTT broker on port 1883 is down. "
            "That broker is stock firmware, not a plugin: restart it and try again.",
            "broker-down",
        )
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


def default_chain() -> list:
    return [
        moonraker_component_failure,
        klipper_import_failure,
        broker_down,
        last_resort_target,
        catch_all,
    ]
