# SPDX-FileCopyrightText: Copyright (C) 2026 unlucio and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Auth: ACL enforcement and multi-client access management.

ACL file: /userdata/bespok3d/auth/acl.json
  {
    "keys": ["<identity>", ...],            # GPG fingerprint (PGP on) or client id (PGP off)
    "roles": { "<identity>": "admin|user" },
    "labels": { "<identity>": "<friendly name>" },
    "tokens": ["<hex>", ...],               # bearer credentials, one per client
    "token_identity": { "<hex>": "<identity>" }
  }

A second client is authorized by an existing authorized client (ADR-0016/0008, flat peers): the new
client POSTs an access request (it proposes its own token), and any already-authorized client grants
it by appending it to the ACL. Mutations are read-modify-write so a grant never clobbers other keys.
"""

import hmac
import json
import re
from typing import Any

from .data_root import DATA_ROOT

ACL_PATH = DATA_ROOT / "auth/acl.json"

# /access/request is unauthenticated, so its inputs are untrusted. Bound and charset-check them so a
# caller cannot store oversized or control-character garbage (the identity is a GPG fingerprint or a
# generated client id; the token is the bearer hex the client proposes for itself).
_IDENTITY_RE = re.compile(r"^[A-Za-z0-9:._-]{1,128}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9]{16,128}$")
_MAX_LABEL = 64
_MAX_PUBLIC_KEY = 8192


def valid_access_request(identity: str, token: str, label: str, public_key: str) -> bool:
    if not _IDENTITY_RE.match(identity) or not _TOKEN_RE.match(token):
        return False
    if len(label) > _MAX_LABEL or not label.isprintable():
        return False
    return len(public_key) <= _MAX_PUBLIC_KEY


def _empty_acl() -> dict[str, Any]:
    return {"keys": [], "roles": {}, "labels": {}, "tokens": [], "token_identity": {}}


def load_acl() -> dict[str, Any]:
    """The stored ACL, or an empty one when the file is absent or unreadable. A file torn by a power
    cut mid-write must leave the daemon answering and refusing rather than crashing every auth check
    on the printer; the user recovers by re-enrolling, which the app already offers. A field stored
    as null falls back to its empty default for the same reason."""
    if not ACL_PATH.exists():
        return _empty_acl()
    try:
        stored = json.loads(ACL_PATH.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return _empty_acl()
    if not isinstance(stored, dict):
        return _empty_acl()
    filled = {name: value for name, value in stored.items() if value is not None}
    result: dict[str, Any] = {**_empty_acl(), **filled}
    return result


def _save_acl(acl: dict[str, Any]) -> None:
    ACL_PATH.parent.mkdir(parents=True, exist_ok=True)
    ACL_PATH.write_text(json.dumps(acl, indent=2))


def is_authorized(fingerprint: str) -> bool:
    return fingerprint in load_acl().get("keys", [])


def is_authorized_token(token: str) -> bool:
    """Whether the bearer credential offered by a caller is one this printer holds.

    The offered token arrives from an unauthenticated request, so it is any text at all. Compared as
    text it takes the constant-time compare outside what it accepts (it holds only ASCII) and the
    printer answers a stranger's malformed token with a crash instead of a refusal, so both sides
    are compared as bytes."""
    # Constant-time compare against every token so response timing cannot recover a token byte by
    # byte. We iterate all entries (no early break on mismatch); a match short-circuits, which is
    # fine since the caller already holds a valid token in that case.
    offered = token.encode(errors="replace")
    return any(hmac.compare_digest(offered, str(valid).encode(errors="replace"))
               for valid in load_acl().get("tokens", []))


def grant_key(identity: str, token: str, role: str = "user", label: str = "") -> None:
    acl = load_acl()
    if identity not in acl["keys"]:
        acl["keys"].append(identity)
    acl["roles"][identity] = role
    acl["labels"][identity] = label
    if token and token not in acl["tokens"]:
        acl["tokens"].append(token)
    if token:
        acl["token_identity"][token] = identity
    _save_acl(acl)


def revoke_key(identity: str) -> None:
    acl = load_acl()
    acl["keys"] = [key for key in acl["keys"] if key != identity]
    acl["roles"].pop(identity, None)
    acl["labels"].pop(identity, None)
    dropped = [token for token, who in acl["token_identity"].items() if who == identity]
    acl["tokens"] = [token for token in acl["tokens"] if token not in dropped]
    for token in dropped:
        acl["token_identity"].pop(token, None)
    _save_acl(acl)


def list_clients() -> list[dict[str, str]]:
    """Authorized clients for display. Never exposes tokens."""
    acl = load_acl()
    roles, labels = acl["roles"], acl["labels"]
    return [
        {"identity": key, "role": roles.get(key, "user"), "label": labels.get(key, "")}
        for key in acl["keys"]
    ]
