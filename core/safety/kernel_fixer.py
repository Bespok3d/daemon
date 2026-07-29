# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Attribute a kernel-module load failure the jinni classified to the plugin that ships the module.

A kernel-module load fails in its own install phase (never a core-service restart), so it carries no
service health; the evidence's `module_diagnosis` holds the jinni's token (e.g. a version-magic
mismatch after an OTA kernel bump). Unlike device_infrastructure's non-plugin causes, this is the
plugin's own stale .ko, so the fixer deactivates the plugin the op is applying and relays the token
for the app to localize. Kept in its own module so the fixer chain stays lean, one concern per file.
"""
from .context import OperationContext
from .decision import Decision, FailureEvidence

_KERNEL_MODULE_PREFIX = "kernel-module:"


def kernel_module_failure(
    evidence: FailureEvidence, ctx: OperationContext, already: list[str]
) -> Decision | None:
    """The plugin the op is applying, blamed with the jinni's kernel-module token; inert on the
    restart-health path, where `module_diagnosis` is empty."""
    token = evidence.module_diagnosis
    if token.startswith(_KERNEL_MODULE_PREFIX) and ctx.plugin_id and ctx.plugin_id not in already:
        return Decision(ctx.plugin_id, token, "kernel-module-failure")
    return None
