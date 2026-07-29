# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
from pydantic import BaseModel, Field


class AccessRequestBody(BaseModel):
    label: str = Field(description="Friendly name for the requesting client (e.g. machine name)")
    identity: str = Field(description="GPG fingerprint (PGP on) or a stable client id (PGP off)")
    token: str = Field(description="Bearer credential the client proposes for itself")
    public_key: str | None = Field(default=None, description="Armored client public key (PGP on)")


class AccessRequestResponse(BaseModel):
    ok: bool = Field(description="True once the request is recorded as pending")
    cert: str = Field(description="The daemon's public server certificate, for the client to pin")


class AccessIdentityBody(BaseModel):
    identity: str = Field(description="Identity of the client to grant or revoke")


class AccessActionResponse(BaseModel):
    ok: bool = Field(description="True on success")


class AccessClient(BaseModel):
    identity: str = Field(description="GPG fingerprint or client id")
    role: str = Field(description="admin or user")
    label: str = Field(description="Friendly client name")


class PendingClient(BaseModel):
    identity: str = Field(description="GPG fingerprint or client id")
    label: str = Field(description="Friendly client name")
    requested_at: str = Field(description="ISO timestamp the request was recorded")


class AccessClientsResponse(BaseModel):
    clients: list[AccessClient] = Field(description="Authorized clients (no tokens exposed)")
    pending: list[PendingClient] = Field(description="Clients awaiting approval")
