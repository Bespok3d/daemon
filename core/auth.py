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

Pending file: /userdata/bespok3d/auth/pending.json
  [ { "identity", "label", "public_key", "token", "requested_at" }, ... ]

A second client is authorized by an existing authorized client (ADR-0016/0008, flat peers): the new
client POSTs an access request (it proposes its own token), and any already-authorized client grants
it by appending it to the ACL. Mutations are read-modify-write so a grant never clobbers other keys.
"""

import hmac
import json
import re
from datetime import datetime, timezone
from typing import Any

from .data_root import DATA_ROOT

ACL_PATH = DATA_ROOT / "auth/acl.json"
PENDING_PATH = DATA_ROOT / "auth/pending.json"
PENDING_CAP = 8

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
    if not ACL_PATH.exists():
        return _empty_acl()
    result: dict[str, Any] = {**_empty_acl(), **json.loads(ACL_PATH.read_text())}
    return result


def _save_acl(acl: dict[str, Any]) -> None:
    ACL_PATH.parent.mkdir(parents=True, exist_ok=True)
    ACL_PATH.write_text(json.dumps(acl, indent=2))


def is_authorized(fingerprint: str) -> bool:
    return fingerprint in load_acl().get("keys", [])


def is_authorized_token(token: str) -> bool:
    # Constant-time compare against every token so response timing cannot recover a token byte by
    # byte. We iterate all entries (no early break on mismatch); a match short-circuits, which is
    # fine since the caller already holds a valid token in that case.
    return any(hmac.compare_digest(token, valid) for valid in load_acl().get("tokens", []))


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


def load_pending() -> list[dict[str, Any]]:
    if not PENDING_PATH.exists():
        return []
    items: list[dict[str, Any]] = json.loads(PENDING_PATH.read_text())
    return items


def _save_pending(items: list[dict[str, Any]]) -> None:
    PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    PENDING_PATH.write_text(json.dumps(items, indent=2))


def add_pending(entry: dict[str, Any], cap: int = PENDING_CAP) -> bool:
    """Record an access request. Returns False when the pending list is full (abuse cap)."""
    items = [item for item in load_pending() if item.get("identity") != entry.get("identity")]
    if len(items) >= cap:
        return False
    items.append({**entry, "requested_at": datetime.now(timezone.utc).isoformat()})
    _save_pending(items)
    return True


def list_pending() -> list[dict[str, str]]:
    """Pending requests for display. Never exposes the proposed token."""
    return [
        {"identity": item["identity"], "label": item.get("label", ""),
         "requested_at": item.get("requested_at", "")}
        for item in load_pending()
    ]


def pop_pending(identity: str) -> dict[str, Any] | None:
    items = load_pending()
    match = next((item for item in items if item.get("identity") == identity), None)
    if match is not None:
        _save_pending([item for item in items if item.get("identity") != identity])
    return match
