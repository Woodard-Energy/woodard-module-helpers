import hashlib
import hmac
import logging
import os
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request

log = logging.getLogger(__name__)

# Returned when WOODARD_SIGNING_SECRET is unset — local dev convenience.
# Wildcard role allows unverified requests through role gates. Only safe
# when the module port isn't exposed (shell enforces the network boundary).
ANONYMOUS_DEV = {"email": "anonymous", "roles": ["*"]}

# Returned when the secret IS set but a request can't be verified (missing
# headers, tampered signature). Empty roles list denies role-gated routes.
ANONYMOUS_DENY = {"email": "anonymous", "roles": []}


def compute_signature(email: str, roles: list[str], secret: str) -> str:
    """Compute HMAC-SHA256 signature matching what the platform shell emits."""
    payload = f"{email}:{','.join(roles)}".encode()
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def current_user(request: Request) -> dict:
    """FastAPI dependency — verify X-Woodard-* headers and return user dict.

    - No WOODARD_SIGNING_SECRET set → ANONYMOUS_DEV (wildcard, local dev).
      Emits a warning log so misconfig in production is visible.
    - Secret set but request unsigned/tampered → ANONYMOUS_DENY (no roles).
      Role gates will deny such requests.
    - Secret set and signature valid → {"email": ..., "roles": [...]}.
    """
    secret = os.environ.get("WOODARD_SIGNING_SECRET", "")
    if not secret:
        log.warning(
            "WOODARD_SIGNING_SECRET not set; returning anonymous with "
            "wildcard role (local dev mode — do not deploy like this)"
        )
        return dict(ANONYMOUS_DEV)

    email = request.headers.get("x-woodard-user", "")
    roles_header = request.headers.get("x-woodard-roles", "")
    sig = request.headers.get("x-woodard-signature", "")

    if not email or not sig:
        return dict(ANONYMOUS_DENY)

    roles = [r.strip() for r in roles_header.split(",") if r.strip()]
    expected = compute_signature(email, roles, secret)
    # Both operands are str (hexdigest). compare_digest rejects mixed types.
    if not hmac.compare_digest(sig, expected):
        log.warning("HMAC mismatch for user=%s", email)
        return dict(ANONYMOUS_DENY)

    return {"email": email, "roles": roles}


def require_role(role: str) -> Callable:
    """FastAPI dependency factory — 403 unless user has `role` or wildcard `*`."""

    def _require_role_dep(user: dict = Depends(current_user)) -> None:  # noqa: B008
        if role in user["roles"] or "*" in user["roles"]:
            return
        raise HTTPException(status_code=403, detail=f"role '{role}' required")

    return _require_role_dep


def require_any_role(*roles: str) -> Callable:
    """FastAPI dependency factory — 403 unless user has any of `roles`."""

    def _require_any_role_dep(user: dict = Depends(current_user)) -> None:  # noqa: B008
        user_roles = set(user["roles"])
        if "*" in user_roles or user_roles & set(roles):
            return
        raise HTTPException(
            status_code=403, detail=f"one of {roles} required"
        )

    return _require_any_role_dep
