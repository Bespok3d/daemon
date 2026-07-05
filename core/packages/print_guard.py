"""Print-safety guards: refuse a plugin op whose action is blocked on the printer right now.

The daemon decides nothing about printing and never translates (ADR-0037). The jinni owns both sides
as machine TOKENS: `blocked_actions()` is the set blocked right now (a running print forbids
restarting Klipper, Moonraker, or the display), and `classify_commands()` tags each command with the
token it would trigger. A guard is then pure set membership: map the op to its required tokens,
refuse if any is blocked, raise `BlockedActionError` carrying the offending tokens for the CLIENT to
localize. The guard's only judgment is WHICH ops to check: a system-wide op always, a per-plugin op
only when its manifest restarts something.
"""

import json
from pathlib import Path

from .. import jinni_client
from ..intent import normalize_install
from .errors import BlockedActionError


def _required_tokens(manifest: dict) -> frozenset[str]:
    # Every command the op could run against a service: the install start commands, the managed
    # services' stop hooks, and the teardown `stop` list (where a display-owning plugin like
    # camera-hw-accel declares the display restart its own init script performs). The jinni tags
    # each with the blocked-action token it would trigger; None means it touches no gated service.
    # No facts: these commands come from `service`/`restart`, which carry no variants, so variant
    # resolution cannot change the token set the guard checks.
    ops = normalize_install(manifest.get("install", {}))
    commands = [*ops["start"], *ops["stops"], *manifest.get("stop", [])]
    return frozenset(
        effect.blocking_token
        for effect in jinni_client.classify_commands(commands)
        if effect.blocking_token is not None
    )


def _refuse_if_blocked(required: frozenset[str]) -> None:
    if not required:
        return
    offending = required & jinni_client.blocked_actions()
    if offending:
        raise BlockedActionError(offending)


def guard_no_print() -> None:
    """Refuse a system-wide plugin op (deactivate/teardown/recover) while anything is blocked.

    These bounce services across all plugins, so the check is unconditional: any blocked action
    means the op is refused, carrying the whole blocked set.
    """
    blocked = jinni_client.blocked_actions()
    if blocked:
        raise BlockedActionError(blocked)


def guard_no_print_during_restart(manifest: dict) -> None:
    """Refuse an op whose own commands would restart a service that is blocked right now."""
    _refuse_if_blocked(_required_tokens(manifest))


def guard_batch_no_print(manifests: list[dict]) -> None:
    """Refuse the whole batch up front if any update needs an action that is blocked right now."""
    _refuse_if_blocked(frozenset().union(*(_required_tokens(m) for m in manifests)) if manifests
                        else frozenset())


def guard_no_print_for_removal(plugin_root: Path, plugin_ids: list[str]) -> None:
    """Refuse removing a plugin whose teardown would restart a blocked service right now."""
    for plugin_id in plugin_ids:
        manifest_path = plugin_root / plugin_id / "manifest.json"
        if manifest_path.exists():
            guard_no_print_during_restart(json.loads(manifest_path.read_text()))
