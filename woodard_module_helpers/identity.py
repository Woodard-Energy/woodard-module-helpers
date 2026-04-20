import hashlib
import hmac
import logging
import os
from collections.abc import Callable

from fastapi import HTTPException, Request

log = logging.getLogger(__name__)

ANONYMOUS = {"email": "anonymous", "roles": ["*"]}


def compute_signature(email: str, roles: list[str], secret: str) -> str:
    """Compute HMAC-SHA256 signature matching what the platform shell emits."""
    payload = f"{email}:{','.join(roles)}".encode()
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def current_user(request: Request) -> dict:
    """FastAPI dependency — verify X-Woodard-* headers and return user dict.

    Invalid/missing signatures → anonymous. Missing WOODARD_SIGNING_SECRET →
    anonymous (useful for local dev). Never raises — downstream code can
    gate on roles via require_role().
    """
    secret = os.environ.get("WOODARD_SIGNING_SECRET", "")
    if not secret:
        log.debug("WOODARD_SIGNING_SECRET not set; returning anonymous")
        return dict(ANONYMOUS)

    email = request.headers.get("x-woodard-user", "")
    roles_header = request.headers.get("x-woodard-roles", "")
    sig = request.headers.get("x-woodard-signature", "")

    if not email or not sig:
        return dict(ANONYMOUS)

    roles = [r.strip() for r in roles_header.split(",") if r.strip()]
    expected = compute_signature(email, roles, secret)
    if not hmac.compare_digest(sig, expected):
        log.warning("HMAC mismatch for user=%s", email)
        return dict(ANONYMOUS)

    return {"email": email, "roles": roles}


def require_role(role: str) -> Callable:
    """FastAPI dependency factory — 403 unless user has `role` or wildcard `*`."""

    def _dep(request: Request) -> None:
        user = current_user(request)
        if role in user["roles"] or "*" in user["roles"]:
            return
        raise HTTPException(status_code=403, detail=f"role '{role}' required")

    return _dep


def require_any_role(*roles: str) -> Callable:
    """FastAPI dependency factory — 403 unless user has any of `roles`."""

    def _dep(request: Request) -> None:
        user = current_user(request)
        user_roles = set(user["roles"])
        if "*" in user_roles or user_roles & set(roles):
            return
        raise HTTPException(
            status_code=403, detail=f"one of {roles} required"
        )

    return _dep
