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


def compute_signature(
    email: str,
    roles: list[str],
    secret: str,
    *,
    user_id: int | None = None,
    display_name: str | None = None,
) -> str:
    """HMAC-SHA256 signature.

    Two canonical formats during the auth-layer migration:

    - Legacy 3-header (today's shell `IdentityMiddleware`): canonical is
      ``f"{email}:{roles_csv}"`` where ``roles_csv`` preserves the input
      order. Selected when EITHER ``user_id`` OR ``display_name`` is None.
    - New 5-header (post-Entra shell `SessionMiddleware`): canonical is
      ``f"{email}|{user_id}|{display_name}|{roles_csv}"`` where
      ``roles_csv`` is sorted ascending. Selected when BOTH ``user_id``
      AND ``display_name`` are non-None.

    The "3-header" / "5-header" naming refers to the count of X-Woodard-*
    HTTP headers transmitted with the request, NOT the internal canonical
    string field count. This dual-format support lets one helper version
    work against both the pre-Entra and post-Entra shells during the
    transition window.
    """
    if user_id is not None and display_name is not None:
        roles_csv = ",".join(sorted(roles))
        payload = f"{email}|{user_id}|{display_name}|{roles_csv}".encode()
    else:
        # Legacy 3-field — preserves the original separator (':') and order.
        roles_csv = ",".join(roles)
        payload = f"{email}:{roles_csv}".encode()
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
    # NOTE: legacy 3-header verification path. Auth-layer plan Task 3
    # extends this function to also verify the new 5-header contract.
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
