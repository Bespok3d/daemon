# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The wire to a real printer's daemon: the same HTTPS calls the app makes.

The certificate is the self-signed one the printer generates at enrollment, so it is not verified
here. The bearer token is read off the printer at run time unless B3D_HIL_TOKEN supplies one, which
keeps every real credential on the machine that owns it and none of them in this repo.
"""
import json
import os
import subprocess

import httpx

from daemon import DEFAULT_PORT

ACL_FILE = "/userdata/bespok3d/auth/acl.json"
PLUGIN_ROOT = "/userdata/bespok3d/usr/local/plugins"
STOCK_SSH_USER = "root"
STOCK_SSH_PASSWORD = "snapmaker"
SSH_TIMEOUT_SECONDS = 30.0
WIRE_TIMEOUT_SECONDS = 180.0


def ssh(printer_address: str, remote_command: str) -> str:
    completed = subprocess.run(
        [
            "sshpass", "-p", os.environ.get("B3D_HIL_SSH_PASS", STOCK_SSH_PASSWORD),
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "LogLevel=ERROR",
            f"{os.environ.get('B3D_HIL_SSH_USER', STOCK_SSH_USER)}@{printer_address}",
            remote_command,
        ],
        capture_output=True, text=True, check=True, timeout=SSH_TIMEOUT_SECONDS,
    )
    return completed.stdout


def printer_token(printer_address: str) -> str:
    """A bearer token this printer accepts, taken from the printer's own access list."""
    supplied = os.environ.get("B3D_HIL_TOKEN", "")
    if supplied:
        return supplied
    tokens = json.loads(ssh(printer_address, f"cat {ACL_FILE}")).get("tokens", [])
    if not tokens:
        raise RuntimeError(
            f"{printer_address} holds no access token, so nothing may call its daemon. "
            "Enroll the printer in the app, or set B3D_HIL_TOKEN to a token it accepts.",
        )
    return str(tokens[0])


class DaemonWire:
    """One printer's daemon, for as long as the suite runs: its address, a token it accepts, and the
    open connection carrying both."""

    def __init__(self, printer_address: str, token: str) -> None:
        self.printer_address = printer_address
        self.connection = httpx.Client(
            base_url=f"https://{printer_address}:{DEFAULT_PORT}",
            headers={"Authorization": f"Bearer {token}"},
            verify=False, timeout=WIRE_TIMEOUT_SECONDS,
        )

    def close(self) -> None:
        self.connection.close()

    def offer_package(self, package: bytes) -> httpx.Response:
        """Upload one package for installation, exactly as the app uploads one."""
        return self.connection.post(
            "/plugins/install",
            files={"file": ("invitro-probe.b3", package, "application/octet-stream")},
            data={"vars_json": "{}"},
        )

    def uninstall(self, plugin_id: str) -> httpx.Response:
        return self.connection.delete(f"/plugins/{plugin_id}")

    def installed_versions(self) -> dict[str, str]:
        """Plugin id to installed version, as the printer reports it to the app."""
        capabilities = self.connection.get("/capabilities")
        capabilities.raise_for_status()
        installed = capabilities.json().get("installed", {})
        return {str(plugin_id): str(version) for plugin_id, version in installed.items()}

    def plugin_files_on_disk(self, plugin_id: str) -> bool:
        """Whether the printer holds a directory for this plugin, which a refused package must not
        leave behind."""
        looked = f"test -d {PLUGIN_ROOT}/{plugin_id} && echo yes || echo no"
        return ssh(self.printer_address, looked).strip() == "yes"
