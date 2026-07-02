"""Golden-fixture pin for the app<->daemon JSON contract.

The committed `contract_fixture.json` is a representative sample of every response whose shape the
app parses raw off the wire. This test keeps that file honest to the Pydantic models: it rebuilds
the sample from the models and asserts the committed JSON matches it. A field renamed or retyped in
`api/schemas/` changes the rebuilt dump, so this test fails until the fixture is regenerated and the
diff is reviewed.

The app side holds a copy of this same fixture (under daemon-client/) and type-checks it against
`daemon-client/contract.ts`, so a field renamed on the app side fails THERE. The two halves meet at
this JSON. The live over-the-wire backstop is the Docker in-vitro lifecycle suite; this pin is the
fast, no-Docker static complement.

Regenerate after an intentional schema change: `UPDATE_CONTRACT_FIXTURE=1 .venv/bin/pytest \
tests/api/test_contract_fixture.py`, then copy the file to the app-side daemon-client/ fixture.
"""
import json
import os
from pathlib import Path
from typing import Any

from api.schemas import (
    CapabilitiesResponse,
    InstallResponse,
    PackResultsResponse,
    PluginConfigResponse,
    PluginRecoveryResult,
    ReconfigureResponse,
    StatusResponse,
)

FIXTURE_PATH = Path(__file__).parent / "contract_fixture.json"


def _sample_phases() -> list[dict[str, Any]]:
    return [
        {
            "id": "extract",
            "label": "Unpack package",
            "ok": True,
            "items": [{"label": "extract files", "ok": True, "output": ""}],
        },
        {
            "id": "restart",
            "label": "Restart services",
            "ok": True,
            "items": [
                {"label": "restart klipper", "ok": True, "output": "klipper ready"},
                {"label": "restart moonraker", "ok": True, "output": ""},
            ],
        },
    ]


def _sample_recovery() -> PluginRecoveryResult:
    return PluginRecoveryResult.model_validate({
        "plugin_id": "spoolman",
        "ok": True,
        "skipped": False,
        "reason": "",
        "log": _sample_phases(),
        "auto_deactivated": None,
        "fix_detail": "",
    })


def _sample_capabilities() -> CapabilitiesResponse:
    return CapabilitiesResponse.model_validate({
        "adapter": "snapmaker-u1",
        "hardware": ["camera-mipi", "rfid-spi"],
        "installed": {"spoolman": "0.1.8"},
        "deactivated": [],
        "firmware_version": "1.4.1",
        "klipper_version": "0.12.0",
        "jinni_version": "0.1.1",
        "capability_flags": ["overlay", "managed-service"],
        "interface_extras": [],
        "preferred_registries": ["github:Bespok3d/main-index/index.json"],
        "endpoints": [{"label": "Spoolman", "url": "http://{host}:7912"}],
    })


def _sample_fixture() -> dict[str, Any]:
    install = InstallResponse.model_validate(
        {"plugin_id": "spoolman", "ok": True, "log": _sample_phases()}
    )
    reconfigure = ReconfigureResponse.model_validate(
        {"plugin_id": "spoolman", "ok": True, "log": _sample_phases()}
    )
    recover = PackResultsResponse(ok=True, results=[_sample_recovery()])
    # The version is a static representative value on purpose: the fixture pins SHAPE, and using the
    # live DAEMON_VERSION would force a regen (and an app-side copy) on every routine bump.
    status = StatusResponse.model_validate({
        "ok": True,
        "version": "0.12.12-dev",
        "printer_uuid": "11111111-2222-3333-4444-555555555555",
    })
    plugin_config = PluginConfigResponse.model_validate(
        {"vars": {"SPOOLMAN_SERVER": "http://spoolman.example:7912"}}
    )
    return {
        "install": install.model_dump(mode="json"),
        "reconfigure": reconfigure.model_dump(mode="json"),
        "recover": recover.model_dump(mode="json"),
        "capabilities": _sample_capabilities().model_dump(mode="json"),
        "status": status.model_dump(mode="json"),
        "plugin_config": plugin_config.model_dump(mode="json"),
    }


def test_contract_fixture_matches_models() -> None:
    expected = _sample_fixture()
    if os.environ.get("UPDATE_CONTRACT_FIXTURE"):
        FIXTURE_PATH.write_text(json.dumps(expected, indent=2) + "\n")
    committed = json.loads(FIXTURE_PATH.read_text())
    assert committed == expected
